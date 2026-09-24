"""Loads config.toml into a typed Config."""
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_DIR / "config.toml"


@dataclass
class Config:
    downloads: Path
    state_dir: Path
    roots: list[Path]
    include_patterns: list[str]
    extra_folders: list[Path]
    aliases: dict[str, list[str]]
    descriptions: dict[str, str]
    claude_exe: str
    claude_timeout_s: float
    ollama_url: str
    ollama_timeout_s: float
    keep_alive: str
    num_ctx: int
    extensions: list[str]
    detection_mode: str
    auto_open: bool
    open_fallback_s: float
    auto_move_on_llm_alone: bool
    pages_to_read: int
    max_chars: int
    min_text_chars: int
    ui: str
    # Set from the command line only, never from config.toml.
    backend: str = "claude"
    model: str = ""


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else PROJECT_DIR / p


def load(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: copy config.example.toml to config.toml and edit it")
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    paths, folders = raw.get("paths", {}), raw.get("folders", {})
    ollama, detection, behavior = raw.get("ollama", {}), raw.get("detection", {}), raw.get("behavior", {})
    claude = raw.get("claude", {})
    mode = detection.get("mode", "strict")
    if mode not in ("strict", "motw"):
        raise ValueError(f"detection.mode must be 'strict' or 'motw', got {mode!r}")
    return Config(
        downloads=_path(paths.get("downloads", "~/Downloads")),
        state_dir=_path(paths.get("state_dir", "state")),
        roots=[_path(p) for p in folders.get("roots", [])],
        include_patterns=folders.get("include_patterns", [r"^[A-Za-z]{2,5}\d{3}$"]),
        extra_folders=[_path(p) for p in folders.get("extra", [])],
        aliases={k.lower(): list(v) for k, v in folders.get("aliases", {}).items()},
        descriptions={k.lower(): v for k, v in folders.get("descriptions", {}).items()},
        claude_exe=claude.get("exe", ""),
        claude_timeout_s=float(claude.get("timeout_s", 90)),
        ollama_url=ollama.get("url", "http://127.0.0.1:11434").rstrip("/"),
        ollama_timeout_s=float(ollama.get("timeout_s", 180)),
        keep_alive=str(ollama.get("keep_alive", "30m")),
        num_ctx=int(ollama.get("num_ctx", 4096)),
        extensions=[e.lower() for e in detection.get("extensions", [".pdf"])],
        detection_mode=mode,
        auto_open=bool(behavior.get("auto_open", True)),
        open_fallback_s=float(behavior.get("open_fallback_s", 20)),
        auto_move_on_llm_alone=bool(behavior.get("auto_move_on_llm_alone", False)),
        pages_to_read=int(behavior.get("pages_to_read", 2)),
        max_chars=int(behavior.get("max_chars", 2000)),
        min_text_chars=int(behavior.get("min_text_chars", 40)),
        ui=behavior.get("ui", "toast"),
    )
