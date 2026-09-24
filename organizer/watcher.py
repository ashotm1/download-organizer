"""Watches the Downloads folder and reports files the browser just finished downloading."""
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)

# Chromium (Edge/Chrome) writes *.crdownload and renames on completion; Firefox uses *.part.
TEMP_SUFFIXES = (".crdownload", ".part", ".partial", ".download", ".tmp")
DEDUP_WINDOW_S = 60


class DownloadWatcher(FileSystemEventHandler):
    def __init__(self, downloads: Path, extensions: list[str], mode: str,
                 on_download: Callable[[Path, bool], None]):
        self.downloads = downloads
        self.extensions = tuple(extensions)
        self.mode = mode
        self.on_download = on_download
        self._recent: dict[str, float] = {}
        self._lock = threading.Lock()
        self._observer: Observer | None = None

    def _wanted(self, path: str) -> bool:
        p = Path(path)
        return p.suffix.lower() in self.extensions and os.path.normcase(str(p.parent)) == \
            os.path.normcase(str(self.downloads))

    def _emit(self, path: str, from_temp: bool) -> None:
        key = os.path.normcase(path)
        now = time.monotonic()
        with self._lock:
            self._recent = {k: t for k, t in self._recent.items() if now - t < DEDUP_WINDOW_S}
            if key in self._recent:
                return
            self._recent[key] = now
        log.info("download detected: %s (from temp file: %s)", path, from_temp)
        self.on_download(Path(path), from_temp)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).lower().endswith(TEMP_SUFFIXES) \
                and self._wanted(event.dest_path):
            self._emit(event.dest_path, from_temp=True)

    def on_created(self, event: FileSystemEvent) -> None:
        # Files that appear directly (not via a temp-file rename) are either copies/moves by the
        # user or the browser's empty placeholder. Only "motw" mode considers them.
        if self.mode == "motw" and not event.is_directory and self._wanted(event.src_path):
            self._emit(event.src_path, from_temp=False)

    def start(self) -> None:
        self._observer = Observer()
        self._observer.schedule(self, str(self.downloads), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        log.info("watching %s (mode=%s)", self.downloads, self.mode)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)


def wait_until_complete(path: Path, timeout_s: float = 600, poll_s: float = 1.0) -> bool:
    """True once the file exists, is non-empty, has a stable size and can be opened for reading."""
    deadline = time.monotonic() + timeout_s
    last_size, stable = -1, 0
    while time.monotonic() < deadline:
        if not path.exists():
            return False
        in_progress = any(Path(f"{path}{s}").exists() for s in TEMP_SUFFIXES)
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        if size > 0 and size == last_size and not in_progress:
            stable += 1
            if stable >= 2:
                try:
                    with open(path, "rb"):
                        return True
                except OSError:
                    stable = 0
        else:
            stable = 0
        last_size = size
        time.sleep(poll_s)
    return False
