"""Claude through the Claude Code CLI in print mode, on the user's subscription (no API key)."""
import glob
import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .ollama_client import LlmError

log = logging.getLogger(__name__)

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

    # Accurate enough to move files on its own confidence: 28/28 in the 2026-09-23 evaluation,
    # re-confirmed 33/33 on 2026-09-28 after adding --strict-mcp-config and 37/37 on 2026-10-05
    # with thinking off (see docs/ROADMAP.md).
    trusted = True

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
               "--strict-mcp-config", "--output-format", "json", "--system-prompt", system,
               # Thinking is on by default with a large budget; off, calls take half the time at the same accuracy.
               "--settings", json.dumps({"alwaysThinkingEnabled": False}),
               "--json-schema", json.dumps(schema)]
        try:
            proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                                  timeout=self.timeout_s, cwd=self._cwd,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            out = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            raise LlmError(f"Claude Code call failed: {e}") from e
        if out.get("is_error") or not isinstance(out.get("structured_output"), dict):
            raise LlmError(f"Claude Code error: {str(out.get('result'))[:200]}")
        self._log_usage(out)
        return out["structured_output"]

    def _log_usage(self, out: dict) -> None:
        # modelUsage sums tokens across every turn of the call; out["usage"] alone is only the last turn.
        usage = next(iter(out.get("modelUsage", {}).values()), {})
        log.info("%s: tokens in=%d cache_read=%d cache_write=%d out=%d (thinking=%d) "
                 "turns=%d api_ms=%d cost=$%.4f", self.name, usage.get("inputTokens", 0),
                 usage.get("cacheReadInputTokens", 0), usage.get("cacheCreationInputTokens", 0),
                 usage.get("outputTokens", 0), usage.get("thinkingTokens", 0), out.get("num_turns", 0),
                 out.get("duration_api_ms", 0), out.get("total_cost_usd", 0.0))
