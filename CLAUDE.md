# Download Organizer: notes for Claude

Read README.md for what the app does and how it decides. Deferred work lives in docs/ROADMAP.md: add to it rather than implementing unrequested features.

## Environment
- Windows 11, no dedicated GPU (Intel Arc 130V integrated), 16 GB RAM. Python is 3.14 from the Python Install Manager (`py`), on PATH via `%LOCALAPPDATA%\Python\bin`; `.venv` is built from it. Always use `.venv\Scripts\python.exe`.
- Model: Claude Haiku via the Claude Code CLI (`claude -p`, the user's subscription) by default. `--backend ollama` switches to local `qwen2.5:3b` at `http://127.0.0.1:11434` (not `localhost`, which stalls on IPv6); the Arc iGPU is enabled by the user environment variable `OLLAMA_IGPU_ENABLE=1`.
- Browser: Edge. Downloads land in `C:\Users\Ashot\Downloads`; course folders are `C:\Users\Ashot\OneDrive\Documents\Ashot\<code>` (OneDrive: never read file contents during discovery, names/stat only).

## Rules for changes
- The model is chosen only by the command-line flags `--backend` / `--model`. Never add an automatic fallback or a model setting in config.toml.
- The model decides; course-code rules are a supporting signal, not the primary decider.
- Never delete user files; moves only, always logged in `state/moves.jsonl` so they can be undone.
- Only browser-completed downloads (`.crdownload` → final rename) trigger processing; files the user copies into Downloads must be ignored.
- Download URLs contain tokens: log and prompt with `motw.clean_url()` only.
- Keep the decision table in `classifier.decide` pure and covered by `tests/test_core.py`.
- Run `.venv\Scripts\python.exe -m unittest discover -s tests -t .` after changes.
