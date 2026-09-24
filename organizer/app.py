"""Wires the watcher, classifier, actions and UI together."""
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import actions, motw
from . import folders as fl
from .classifier import ASK, AUTO, Classifier, DocInfo, build_llm, suggested_parent
from .config import Config
from .extract import extract
from .history import History
from .notifier import Notifier
from .ollama_client import LlmError
from .ui import UI, ReviewRow
from .watcher import DownloadWatcher, wait_until_complete

log = logging.getLogger(__name__)
FOLDER_REFRESH_S = 300


@dataclass
class Pending:
    id: str
    path: Path
    kind: str  # "ask" | "no_match" | "no_text" | "error" | "undone"
    folder: fl.Folder | None = None
    suggested_new: str | None = None
    doc: DocInfo | None = None

    def suggestion(self) -> str:
        if self.kind == "ask" and self.folder:
            return f"→ {self.folder.key}"
        if self.kind == "no_match" and self.suggested_new:
            return f"new folder “{self.suggested_new}”"
        return {"no_text": "no text (scanned?)", "error": "unreadable", "undone": "move undone"}.get(
            self.kind, "no match")

    def primary_label(self) -> str | None:
        if self.kind == "ask" and self.folder:
            return "Move"
        if self.kind == "no_match" and self.suggested_new:
            return "Create & move"
        return None


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.history = History(cfg.state_dir)
        self.mover = actions.Mover(cfg.state_dir)
        self.llm = build_llm(cfg)
        self.classifier = Classifier(cfg, self.llm, self.history)
        self.ui = UI()
        self.notifier = Notifier(cfg.ui, self.ui)
        self.jobs = ThreadPoolExecutor(1, thread_name_prefix="download")  # one at a time: CPU-bound model
        self.work = ThreadPoolExecutor(1, thread_name_prefix="action")    # user actions never wait on the model
        self.watcher = DownloadWatcher(cfg.downloads, cfg.extensions, cfg.detection_mode, self.on_download)
        self.paused = False
        self.model_status = "checking model…"
        self._pending: dict[str, Pending] = {}
        self._lock = threading.Lock()
        self._folders: list[fl.Folder] = []
        self._folders_at = 0.0
        self.tray = None

    # --- lifecycle -------------------------------------------------------------------------
    def run(self) -> None:
        from . import tray
        self.refresh_folders(force=True)
        self.watcher.start()
        threading.Thread(target=self._check_model, daemon=True).start()
        self.tray = tray.create(self)
        self.tray.run_detached()
        self.ui.run()  # blocks until quit

    def quit(self) -> None:
        self.watcher.stop()
        if self.tray:
            self.tray.stop()
        self.ui.quit()

    def _check_model(self) -> None:
        ok, msg = self.llm.status()
        self.model_status = self.llm.name if ok else f"{self.llm.name} unavailable"
        log.info(msg)
        if not ok:
            log.warning(msg)
            self.notifier.show("Download Organizer: model unavailable",
                               f"{msg}. Until then, course codes are used but every move asks first.", [])
            return
        try:
            self.llm.warmup()
        except LlmError as e:
            log.warning("warmup failed: %s", e)

    # --- folders -----------------------------------------------------------------------------
    def folders(self) -> list[fl.Folder]:
        self.refresh_folders()
        return self._folders

    def refresh_folders(self, force: bool = False) -> None:
        if force or time.monotonic() - self._folders_at > FOLDER_REFRESH_S:
            self._folders = fl.discover(self.cfg, self.history.learned_folders())
            self._folders_at = time.monotonic()
            log.info("destinations: %s", ", ".join(f.key for f in self._folders))

    # --- pipeline ----------------------------------------------------------------------------
    def on_download(self, path: Path, from_temp: bool) -> None:
        if self.paused:
            log.info("paused, ignoring %s", path.name)
            return
        self.jobs.submit(self._safe, self._process, path, from_temp)

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("%s failed", fn.__name__)

    def _process(self, path: Path, from_temp: bool) -> None:
        if not wait_until_complete(path):
            log.info("gave up waiting for %s", path.name)
            return
        # A .crdownload rename already proves a browser download; the mark is only extra context then.
        mark = motw.read(path) if from_temp else motw.read_with_retry(path)
        if not from_temp and not (mark and mark.from_internet):
            log.info("skipping %s: not a browser download", path.name)
            return
        opener = actions.Opener(path, self.cfg.auto_open, self.cfg.open_fallback_s)
        name = path.name
        ex = extract(path, self.cfg.pages_to_read, self.cfg.max_chars)
        doc = DocInfo(name, ex.text, ex.title, motw.source_key(mark), motw.clean_url(mark.referrer_url or mark.host_url) if mark else None)

        if ex.error or not ex.has_text(self.cfg.min_text_chars):
            kind = "error" if ex.error else "no_text"
            p = self._add_pending(Pending(self._new_id(), path, kind, doc=doc))
            opener.open(path)
            detail = f"Couldn't read it ({ex.error})." if ex.error else "It has no text layer (scanned?)."
            self._notify_pending(p, f"Not sorted: {name}", f"{detail} It stays in Downloads.",
                                 [("Pick folder", "pick"), ("Leave", "leave")])
            return

        decision = self.classifier.classify(self.folders(), doc)
        if decision.tier == AUTO:
            try:
                move_id, dest = self.mover.move(path, decision.folder.path)
            except OSError as e:
                log.warning("auto-move failed, asking instead: %s", e)
                decision.tier, decision.reason = ASK, f"{decision.reason} (move failed: {e})"
            else:
                self.history.add(file=name, folder=decision.folder.path, how="auto", move_id=move_id,
                                 source_key=doc.source_key, source_url=doc.source_url, snippet=doc.text)
                opener.open(dest)
                self._notify_moved(name, dest, move_id, decision.folder.key, decision.reason)
                return

        opener.open(path)
        if decision.tier == ASK:
            p = self._add_pending(Pending(self._new_id(), path, "ask", folder=decision.folder, doc=doc))
            self._notify_pending(p, f"Move to {decision.folder.key}?", f"{name}\n{decision.reason}",
                                 [("Move", "primary"), ("Pick other", "pick"), ("Leave", "leave")])
        else:
            p = self._add_pending(Pending(self._new_id(), path, "no_match", suggested_new=decision.suggested_new, doc=doc))
            parent = suggested_parent(self.cfg)
            if decision.suggested_new and parent:
                self._notify_pending(p, "No matching folder",
                                     f"{name}\nCreate “{decision.suggested_new}” in {parent.name} and move it there?",
                                     [("Create & move", "primary"), ("Pick folder", "pick"), ("Leave", "leave")])
            else:
                self._notify_pending(p, "No matching folder", f"{name} stays in Downloads.",
                                     [("Pick folder", "pick"), ("Leave", "leave")])

    # --- notifications -----------------------------------------------------------------------
    def _notify_moved(self, name: str, dest: Path, move_id: str, folder_label: str, reason: str) -> None:
        def on_choice(key: str) -> None:
            if key == "undo":
                self.work.submit(self._safe, self._undo, move_id)
            elif key in ("reveal", "body"):
                actions.reveal(dest)
        self.notifier.show(f"Moved to {folder_label}", f"{name}\n{reason}",
                           [("Undo", "undo"), ("Show in folder", "reveal")], on_choice)

    def _notify_pending(self, p: Pending, title: str, body: str, buttons: list[tuple[str, str]]) -> None:
        def on_choice(key: str) -> None:
            if key == "body":
                self.open_review()
            elif key != "dismiss":
                self.work.submit(self._safe, self._handle_pending, p.id, key)
        self.notifier.show(title, body, buttons, on_choice, sticky=True)

    # --- pending items -----------------------------------------------------------------------
    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:8]

    def _add_pending(self, p: Pending) -> Pending:
        with self._lock:
            self._pending[p.id] = p
        self._refresh_review()
        return p

    def _drop_pending(self, pid: str) -> None:
        with self._lock:
            self._pending.pop(pid, None)
        self._refresh_review()

    def _handle_pending(self, pid: str, action: str) -> None:
        with self._lock:
            p = self._pending.get(pid)
        if p is None:
            return
        if not p.path.exists():
            log.info("%s is gone from Downloads; dropping it", p.path.name)
            self._drop_pending(pid)
            return
        if action == "leave":
            self._drop_pending(pid)
        elif action == "open":
            actions.open_path(p.path)
        elif action == "primary":
            if p.kind == "ask" and p.folder:
                self._move_pending(p, p.folder.path, "confirmed")
            elif p.kind == "no_match" and p.suggested_new and suggested_parent(self.cfg):
                target = suggested_parent(self.cfg) / p.suggested_new
                target.mkdir(parents=True, exist_ok=True)
                self._remember_folder(target)
                self._move_pending(p, target, "created")
        elif action == "pick":
            initial = suggested_parent(self.cfg)
            self.ui.call(self.ui.pick_folder, f"Where should “{p.path.name}” go?", self.folders(), initial,
                         lambda dest: self.work.submit(self._safe, self._picked, pid, dest))

    def _picked(self, pid: str, dest: Path | None) -> None:
        with self._lock:
            p = self._pending.get(pid)
        if dest is None or p is None or not p.path.exists():
            return
        dest.mkdir(parents=True, exist_ok=True)
        self._remember_folder(dest)
        self._move_pending(p, dest, "picked")

    def _remember_folder(self, path: Path) -> None:
        if fl.find(self.folders(), path) is None:
            self.history.add_learned_folder(path)
            self.refresh_folders(force=True)

    def _move_pending(self, p: Pending, dest_dir: Path, how: str) -> None:
        try:
            move_id, dest = self.mover.move(p.path, dest_dir)
        except OSError as e:
            self.notifier.show("Couldn't move file", f"{p.path.name}: {e}", [])
            return
        doc = p.doc
        self.history.add(file=p.path.name, folder=dest_dir, how=how, move_id=move_id,
                         source_key=doc.source_key if doc else None, source_url=doc.source_url if doc else None,
                         snippet=doc.text if doc else "")
        self._drop_pending(p.id)
        self._notify_moved(p.path.name, dest, move_id, dest_dir.name, "")

    def _undo(self, move_id: str) -> None:
        back = self.mover.undo(move_id)
        if back is None:
            self.notifier.show("Nothing to undo", "The moved file no longer exists where it was put.", [])
            return
        self.history.mark_undone(move_id)
        p = self._add_pending(Pending(self._new_id(), back, "undone"))
        self._notify_pending(p, "Moved back to Downloads", f"{back.name}\nWhere should it go instead?",
                             [("Pick folder", "pick"), ("Leave", "leave")])

    # --- tray actions ------------------------------------------------------------------------
    def status_text(self) -> str:
        with self._lock:
            n = len(self._pending)
        state = "Paused" if self.paused else "Watching Downloads"
        return f"{state} · {n} pending · {self.model_status}"

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        log.info("paused" if self.paused else "resumed")

    def undo_last(self) -> None:
        move_id = self.mover.last_undoable()
        if move_id:
            self.work.submit(self._safe, self._undo, move_id)
        else:
            self.notifier.show("Nothing to undo", "No moves recorded yet.", [])

    def open_state_dir(self) -> None:
        actions.reveal(self.cfg.state_dir)

    def _review_rows(self) -> list[ReviewRow]:
        with self._lock:
            items = list(self._pending.values())
        return [ReviewRow(p.id, p.path.name, p.suggestion(), p.primary_label()) for p in items]

    def _on_review_action(self, pid: str, action: str) -> None:
        self.work.submit(self._safe, self._handle_pending, pid, action)

    def open_review(self) -> None:
        self.ui.call(lambda: self.ui.show_review(self._review_rows(), self._on_review_action))

    def _refresh_review(self) -> None:
        def refresh() -> None:
            if self.ui.review_is_open():
                self.ui.show_review(self._review_rows(), self._on_review_action)
        self.ui.call(refresh)
