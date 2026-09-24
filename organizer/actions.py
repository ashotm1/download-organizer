"""File operations: move with undo log, open, reveal. Never deletes anything."""
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


def unique_destination(folder: Path, name: str) -> Path:
    dest = folder / name
    stem, suffix = os.path.splitext(name)
    n = 1
    while dest.exists():
        dest = folder / f"{stem} ({n}){suffix}"
        n += 1
    return dest


def _move_with_retry(src: Path, dest_dir: Path, name: str | None = None,
                     attempts: int = 15, delay_s: float = 2.0) -> Path:
    """Retries while another program (e.g. a PDF viewer) holds the file open."""
    for i in range(attempts):
        dest = unique_destination(dest_dir, name or src.name)
        try:
            return Path(shutil.move(str(src), str(dest)))
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay_s)
    raise AssertionError("unreachable")


class Mover:
    def __init__(self, state_dir: Path):
        self._log_path = state_dir / "moves.jsonl"
        self._lock = threading.Lock()

    def _append(self, rec: dict) -> None:
        with self._lock, open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _records(self) -> list[dict]:
        if not self._log_path.exists():
            return []
        out = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def move(self, src: Path, dest_dir: Path) -> tuple[str, Path]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _move_with_retry(src, dest_dir)
        move_id = uuid.uuid4().hex[:12]
        self._append({"id": move_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "src": str(src), "dest": str(dest)})
        log.info("moved %s -> %s", src, dest)
        return move_id, dest

    def last_undoable(self) -> str | None:
        undone, moves = set(), []
        for r in self._records():
            if "undo_of" in r:
                undone.add(r["undo_of"])
            else:
                moves.append(r)
        return next((m["id"] for m in reversed(moves) if m["id"] not in undone), None)

    def undo(self, move_id: str) -> Path | None:
        rec = next((r for r in self._records() if r.get("id") == move_id), None)
        if rec is None:
            return None
        dest = Path(rec["dest"])
        if not dest.exists():
            log.warning("cannot undo %s: %s no longer exists", move_id, dest)
            return None
        src = Path(rec["src"])
        back = _move_with_retry(dest, src.parent, src.name)
        self._append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "undo_of": move_id, "restored": str(back)})
        log.info("undo %s: %s -> %s", move_id, dest, back)
        return back


def open_path(path: Path) -> None:
    try:
        os.startfile(str(path))
    except OSError as e:
        log.warning("could not open %s: %s", path, e)


def reveal(path: Path) -> None:
    """Opens Explorer with the file selected (or the folder itself)."""
    if path.is_dir():
        os.startfile(str(path))
    else:
        subprocess.Popen(f'explorer /select,"{path}"')


class Opener:
    """Opens a download exactly once: from its final location, or from Downloads if sorting is slow."""

    def __init__(self, path: Path, enabled: bool, fallback_s: float):
        self._path, self._enabled, self._done = path, enabled, False
        self._lock = threading.Lock()
        self._timer = None
        if enabled and fallback_s > 0:
            self._timer = threading.Timer(fallback_s, self.open, args=(path,))
            self._timer.daemon = True
            self._timer.start()

    def open(self, path: Path | None = None) -> None:
        with self._lock:
            if self._done or not self._enabled:
                return
            self._done = True
        if self._timer:
            self._timer.cancel()
        open_path(path or self._path)

    def cancel(self) -> None:
        with self._lock:
            self._done = True
        if self._timer:
            self._timer.cancel()
