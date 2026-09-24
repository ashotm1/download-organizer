"""Claude through the Claude Code CLI in print mode, on the user's subscription (no API key)."""
import glob
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .ollama_client import LlmError

# The CLI ships inside the VS Code extension; its folder name changes with every update.
_EXTENSION_EXE = ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe"


def _version_key(path: str) -> tuple[int, ...]:
    m = re.search(r"claude-code-(\d+(?:\.\d+)*)", path)
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def find_exe(configured: str = "") -> str | None:
    if configured:
        return configured if Path(configured).exists() else None
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    found = sorted(glob.glob(str(Path.home() / _EXTENSION_EXE)), key=_version_key)
    return found[-1] if found else None


class ClaudeCode:
    """Same interface as Ollama: status(), warmup(), chat_json()."""

    trusted = True  # accurate enough to move files on its own confidence (28/28 in the evaluation)

    def __init__(self, model: str, exe: str, timeout_s: float):
        self.model, self.timeout_s = model, timeout_s
        self.exe = find_exe(exe)
        self.name = f"Claude {model}"
        # A neutral working directory keeps project files such as CLAUDE.md out of the prompt.
        self._cwd = tempfile.mkdtemp(prefix="download_organizer_claude_")

    def status(self) -> tuple[bool, str]:
        if not self.exe:
            return False, "Claude Code CLI not found (install the VS Code extension or set [claude] exe)"
        return True, f"{self.name} via Claude Code"

    def warmup(self) -> None:
        pass

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        if not self.exe:
            raise LlmError("Claude Code CLI not found")
        cmd = [self.exe, "-p", "--model", self.model, "--tools", "", "--no-session-persistence",
               "--output-format", "json", "--system-prompt", system, "--json-schema", json.dumps(schema)]
        try:
            proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                                  timeout=self.timeout_s, cwd=self._cwd,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            out = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            raise LlmError(f"Claude Code call failed: {e}") from e
        if out.get("is_error") or not isinstance(out.get("structured_output"), dict):
            raise LlmError(f"Claude Code error: {str(out.get('result'))[:200]}")
        return out["structured_output"]
