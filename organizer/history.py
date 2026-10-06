"""What the user filed where. Drives learned sources, few-shot examples and learned folders."""
import json
import logging
import os
import threading
import time
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class History:
    def __init__(self, state_dir: Path):
        self._path = state_dir / "history.jsonl"
        self._learned_path = state_dir / "learned_folders.json"
        self._lock = threading.Lock()
        self._records: list[dict] = []
        self._undone: set[str] = set()
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                try:
                    self._ingest(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("skipping bad history line")

    def _ingest(self, rec: dict) -> None:
        if "undo_of" in rec:
            self._undone.add(rec["undo_of"])
        else:
            self._records.append(rec)

    def _append(self, rec: dict) -> None:
        with self._lock:
            self._ingest(rec)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def add(self, *, file: str, folder: Path, how: str, move_id: str | None,
            source_key: str | None, source_url: str | None, snippet: str, reason: str = "") -> None:
        self._append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": file, "folder": str(folder), "how": how,
            "move_id": move_id, "source_key": source_key, "source_url": source_url, "snippet": snippet[:200],
            "reason": reason,
        })

    def mark_undone(self, move_id: str) -> None:
        self._append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "undo_of": move_id})

    def _valid(self) -> list[dict]:
        with self._lock:
            return [r for r in self._records if r.get("move_id") not in self._undone]

    def source_folder(self, source_key: str | None) -> str | None:
        """The folder this source was always filed into, if the history is consistent."""
        if not source_key:
            return None
        folders = defaultdict(str)
        for r in self._valid():
            if r.get("source_key") == source_key:
                folders[_norm(r["folder"])] = r["folder"]
        return next(iter(folders.values())) if len(folders) == 1 else None

    def examples(self, limit: int = 8) -> list[dict]:
        """Recent user-confirmed decisions, newest first, one per file name."""
        out, seen = [], set()
        for r in reversed(self._valid()):
            if r.get("how") == "auto" or r["file"].lower() in seen:
                continue
            seen.add(r["file"].lower())
            out.append(r)
            if len(out) >= limit:
                break
        return out

    def learned_folders(self) -> list[Path]:
        try:
            return [Path(p) for p in json.loads(self._learned_path.read_text(encoding="utf-8"))]
        except (OSError, json.JSONDecodeError):
            return []

    def add_learned_folder(self, path: Path) -> None:
        with self._lock:
            current = self.learned_folders()
            if _norm(path) not in {_norm(p) for p in current}:
                current.append(path)
                self._learned_path.write_text(json.dumps([str(p) for p in current], indent=2), encoding="utf-8")
