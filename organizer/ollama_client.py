"""Minimal Ollama HTTP client (stdlib only)."""
import json
import time
import urllib.error
import urllib.request


class LlmError(Exception):
    pass


OllamaError = LlmError


RETRY_AFTER_S = 60  # after a refused connection, don't stall every download on it


class Ollama:
    trusted = False  # a 3B model is too unreliable to move files on its own confidence

    def __init__(self, url: str, model: str, timeout_s: float, keep_alive: str, num_ctx: int):
        self.url, self.model, self.timeout_s = url, model, timeout_s
        self.keep_alive, self.num_ctx = keep_alive, num_ctx
        self._down_until = 0.0
        self.name = f"local {model}"

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        if time.monotonic() < self._down_until:
            raise OllamaError("unreachable (recently refused)")
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            if isinstance(getattr(e, "reason", e), ConnectionRefusedError):
                self._down_until = time.monotonic() + RETRY_AFTER_S
            raise OllamaError(str(e)) from e

    def status(self) -> tuple[bool, str]:
        self._down_until = 0.0
        try:
            models = [m.get("name", "") for m in self._request("/api/tags", timeout=3).get("models", [])]
        except OllamaError as e:
            return False, f"Ollama is not reachable at {self.url} ({e})"
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if wanted not in models:
            return False, f"Model {self.model} is not pulled. Run: ollama pull {self.model}"
        return True, f"Ollama ready with {self.model}"

    def warmup(self) -> None:
        """Loads the model into memory so the first download is not a cold start."""
        self._request("/api/generate", {"model": self.model, "prompt": "", "keep_alive": self.keep_alive})

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        resp = self._request("/api/chat", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        })
        content = resp.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise OllamaError(f"model returned invalid JSON: {content[:200]!r}") from e
