"""Entry point.

    python -m organizer                 run the background organizer (tray icon)
    python -m organizer --check         show config, destinations and model status
    python -m organizer --classify F    dry run: show where F would go, without moving it

The model is Claude Haiku (via the Claude Code CLI on your subscription) unless a flag says otherwise:
    --backend ollama [--model qwen2.5:3b]    local model
    --model sonnet                           another Claude model
"""
import argparse
import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config as config_mod


def _setup_logging(state_dir: Path, console: bool) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [RotatingFileHandler(state_dir / "app.log", maxBytes=1_000_000,
                                                           backupCount=3, encoding="utf-8")]
    if console and sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _already_running() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\DownloadOrganizer")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def _check(cfg) -> None:
    from .folders import discover
    from .history import History
    from .classifier import build_llm
    print(f"Downloads: {cfg.downloads}  (detection: {cfg.detection_mode})")
    folders = discover(cfg, History(cfg.state_dir).learned_folders())
    print(f"Destinations ({len(folders)}):")
    for f in folders:
        print(f"  {f.key:<12} {f.path}")
        print(f"  {'':<12} e.g. {', '.join(f.samples[:4]) or '(empty)'}")
    ok, msg = build_llm(cfg).status()
    print(("OK  " if ok else "!!  ") + msg)


def _classify(cfg, file: Path) -> None:
    from . import motw
    from .classifier import Classifier, DocInfo, build_llm
    from .extract import extract
    from .folders import discover
    from .history import History
    history = History(cfg.state_dir)
    mark = motw.read(file)
    ex = extract(file, cfg.pages_to_read, cfg.max_chars)
    print(f"File: {file.name}")
    if mark:
        print(f"From: {motw.clean_url(mark.referrer_url or mark.host_url)} (zone {mark.zone_id})")
    if ex.error or not ex.has_text(cfg.min_text_chars):
        print(f"Not classifiable: {ex.error or 'no text layer'}")
        return
    doc = DocInfo(file.name, ex.text, ex.title, motw.source_key(mark),
                  motw.clean_url((mark.referrer_url or mark.host_url) if mark else None))
    d = Classifier(cfg, build_llm(cfg), history).classify(discover(cfg, history.learned_folders()), doc)
    print(f"Decision: {d.tier}  folder={d.folder.key if d.folder else None}  new={d.suggested_new}")
    print(f"Reason:   {d.reason}\nSignals:  {d.signals}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="organizer", description="Sorts browser-downloaded PDFs into folders.")
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument("--check", action="store_true", help="show destinations and model status")
    parser.add_argument("--classify", type=Path, metavar="FILE", help="dry run for one file")
    parser.add_argument("--backend", choices=["claude", "ollama"], default="claude",
                        help="which model service to use (default: claude)")
    parser.add_argument("--model", default="", help="model name (default: haiku for claude, qwen2.5:3b for ollama)")
    args = parser.parse_args()
    cfg = config_mod.load(args.config)
    cfg.backend, cfg.model = args.backend, args.model
    interactive = args.check or args.classify
    _setup_logging(cfg.state_dir, console=not interactive)
    if args.check:
        return _check(cfg)
    if args.classify:
        return _classify(cfg, args.classify)
    if _already_running():
        logging.getLogger(__name__).info("already running; exiting")
        return
    from .app import App
    App(cfg).run()


if __name__ == "__main__":
    main()
