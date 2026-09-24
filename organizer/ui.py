"""Tk-based dialogs: folder picker, review window and fallback popups. Everything runs on the Tk thread."""
import logging
import queue
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, simpledialog, ttk
from typing import Callable

from .folders import Folder

log = logging.getLogger(__name__)


@dataclass
class ReviewRow:
    id: str
    filename: str
    suggestion: str  # human-readable suggestion, e.g. "cs101" or "new folder cs285"
    primary_label: str | None  # e.g. "Move", "Create & move"; None when there is nothing to accept


class UI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Download Organizer")
        self._q: queue.Queue = queue.Queue()
        self._popups: list[tk.Toplevel] = []
        self._review: tk.Toplevel | None = None
        self.root.after(100, self._pump)

    # --- threading -------------------------------------------------------------------------
    def call(self, fn: Callable, *args) -> None:
        """Schedules fn(*args) on the Tk thread. Safe to call from any thread."""
        self._q.put((fn, args))

    def _pump(self) -> None:
        while True:
            try:
                fn, args = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                log.exception("UI callback failed")
        self.root.after(100, self._pump)

    def run(self) -> None:
        self.root.mainloop()

    def quit(self) -> None:
        self.call(self.root.quit)

    # --- folder picker ---------------------------------------------------------------------
    def pick_folder(self, title: str, folders: list[Folder], initial_dir: Path | None,
                    on_result: Callable[[Path | None], None]) -> None:
        win = tk.Toplevel(self.root)
        win.title(title)
        win.attributes("-topmost", True)
        win.resizable(False, True)
        ttk.Label(win, text=title, padding=(10, 8, 10, 4), wraplength=360).pack(anchor="w")
        lb = tk.Listbox(win, height=min(14, max(4, len(folders))), width=48, activestyle="dotbox")
        for f in folders:
            lb.insert("end", f.key)
        lb.pack(fill="both", expand=True, padx=10)
        done = {"sent": False}

        def finish(result: Path | None) -> None:
            if not done["sent"]:
                done["sent"] = True
                win.destroy()
                on_result(result)

        def choose(_event=None) -> None:
            sel = lb.curselection()
            if sel:
                finish(folders[sel[0]].path)

        def browse() -> None:
            path = filedialog.askdirectory(parent=win, initialdir=str(initial_dir or Path.home()),
                                           title="Choose destination folder")
            if path:
                finish(Path(path))

        def new_folder() -> None:
            parent = filedialog.askdirectory(parent=win, initialdir=str(initial_dir or Path.home()),
                                             title="Create the new folder inside…")
            if not parent:
                return
            name = simpledialog.askstring("New folder", f"Folder name inside\n{parent}:", parent=win)
            if name and name.strip():
                finish(Path(parent) / name.strip())

        lb.bind("<Double-Button-1>", choose)
        lb.bind("<Return>", choose)
        buttons = ttk.Frame(win, padding=10)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Move here", command=choose).pack(side="left")
        ttk.Button(buttons, text="Browse…", command=browse).pack(side="left", padx=6)
        ttk.Button(buttons, text="New folder…", command=new_folder).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=lambda: finish(None)).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        self._center(win)
        win.focus_force()

    # --- fallback popups -------------------------------------------------------------------
    def popup(self, title: str, body: str, buttons: list[tuple[str, str]],
              on_choice: Callable[[str], None], timeout_s: float | None) -> None:
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        frame = ttk.Frame(win, padding=12, relief="solid", borderwidth=1)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=("Segoe UI", 10, "bold"), wraplength=340).pack(anchor="w")
        ttk.Label(frame, text=body, wraplength=340, padding=(0, 4, 0, 8)).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x")
        done = {"sent": False}

        def finish(key: str | None) -> None:
            if done["sent"]:
                return
            done["sent"] = True
            if win in self._popups:
                self._popups.remove(win)
            win.destroy()
            self._restack()
            if key is not None:
                on_choice(key)

        for label, key in buttons:
            ttk.Button(row, text=label, command=lambda k=key: finish(k)).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="✕", width=3, command=lambda: finish("dismiss")).pack(side="right")
        self._popups.append(win)
        self._restack()
        if timeout_s:
            win.after(int(timeout_s * 1000), lambda: finish("dismiss"))

    def _restack(self) -> None:
        y = self.root.winfo_screenheight() - 60
        for win in reversed(self._popups):
            win.update_idletasks()
            w, h = max(win.winfo_reqwidth(), 360), win.winfo_reqheight()
            y -= h + 8
            win.geometry(f"{w}x{h}+{self.root.winfo_screenwidth() - w - 16}+{y}")

    # --- review window ---------------------------------------------------------------------
    def show_review(self, rows: list[ReviewRow], on_action: Callable[[str, str], None]) -> None:
        """Lists pending downloads. on_action(row_id, action) with action in primary/pick/leave/open."""
        if self._review is None or not self._review.winfo_exists():
            self._review = tk.Toplevel(self.root)
            self._review.title("Download Organizer — pending")
            self._review.attributes("-topmost", True)
        win = self._review
        for child in win.winfo_children():
            child.destroy()
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        if not rows:
            ttk.Label(body, text="Nothing pending. 🎉", padding=20).pack()
        for r in rows:
            line = ttk.Frame(body, padding=(0, 4))
            line.pack(fill="x")
            ttk.Label(line, text=r.filename, width=44, anchor="w").pack(side="left")
            ttk.Label(line, text=r.suggestion, width=24, anchor="w", foreground="#555").pack(side="left")
            if r.primary_label:
                ttk.Button(line, text=r.primary_label,
                           command=lambda i=r.id: on_action(i, "primary")).pack(side="left", padx=2)
            ttk.Button(line, text="Pick…", command=lambda i=r.id: on_action(i, "pick")).pack(side="left", padx=2)
            ttk.Button(line, text="Open", command=lambda i=r.id: on_action(i, "open")).pack(side="left", padx=2)
            ttk.Button(line, text="Leave", command=lambda i=r.id: on_action(i, "leave")).pack(side="left", padx=2)
        win.deiconify()
        win.lift()
        win.focus_force()

    def review_is_open(self) -> bool:
        return self._review is not None and self._review.winfo_exists()

    def _center(self, win: tk.Toplevel) -> None:
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{(win.winfo_screenwidth() - w) // 2}+{(win.winfo_screenheight() - h) // 3}")
