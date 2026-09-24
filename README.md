# Download Organizer

A background tray app that watches `Downloads`. When the browser finishes downloading a PDF, it reads the first pages, decides which course folder it belongs in (e.g. cs101, math201) and moves it there, asking first whenever it is not sure. The model is **Claude Haiku**, called through the Claude Code CLI on your Claude subscription. No API key is needed, but each PDF's first-page text is sent to Anthropic. A local model is available with a flag, `--backend ollama` ([Ollama](https://ollama.com) with `qwen2.5:3b`). There is no automatic fallback: only the command-line flag changes the model.

## Setup

```powershell
# 0. Settings: copy config.example.toml to config.toml, then set your folders and course descriptions
# 1. Python environment (Anaconda's Python 3.13 is not on PATH, so call it directly)
C:\Users\Ashot\anaconda3\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Model: Claude Haiku needs the Claude Code VS Code extension (its claude.exe is found automatically).
#    Only for --backend ollama: install Ollama, then
ollama pull qwen2.5:3b

# 3. Check that folders and model are found
.venv\Scripts\python.exe -m organizer --check

# 4. Run it (tray icon appears); or install it to start at login
.venv\Scripts\pythonw.exe run.pyw
powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1          # -Remove to undo
```

Use a different model (command line only):

```powershell
.venv\Scripts\pythonw.exe run.pyw --backend ollama            # local qwen2.5:3b
.venv\Scripts\pythonw.exe run.pyw --model sonnet              # another Claude model
```

Dry run on any file, without moving it:

```powershell
.venv\Scripts\python.exe -m organizer --classify "C:\Users\Ashot\Downloads\some.pdf"
```

## What happens to a download

| Situation | What you see |
|---|---|
| Claude is highly confident, **or** two signals agree (course code, past downloads from the same Canvas course, the model) | Moved automatically, opened from its new location, notification with **Undo** / **Show in folder** |
| Only one signal, or signals disagree | Stays in Downloads and opens; notification **Move to X?** with **Move** / **Pick other** / **Leave** |
| No folder fits | Opens; **Create "cs285" and move?** when a new course code is found, else **Pick folder** / **Leave** |
| PDF has no text (scanned) or can't be read | Opens; alert that it was not sorted, with **Pick folder** / **Leave** |

Unanswered questions stay in **Review pending…** (tray icon, double-click).

The PDF is always opened (`behavior.auto_open`). Edge's own "Open file" link points at the old path once a file moves and Edge offers no way to update it, so the organizer opens the file itself. If sorting takes longer than `open_fallback_s` it opens the file from Downloads right away instead of making you wait.

## How it decides

1. **Only real downloads.** Edge writes `name.pdf.crdownload` and renames it when done; only that rename triggers processing. Files you copy or move into Downloads are ignored. (`detection.mode = "motw"` widens this to any file carrying the internet Mark of the Web.)
2. **Text.** First `pages_to_read` pages, the PDF title, and the download source from the file's Mark of the Web (`Zone.Identifier`: Canvas page URL, query strings stripped).
3. **Signals.**
   - *Course code:* the folder name `cs101` matches `CS 101`, `CS101`, `cs-101`, `CompSci 101`… in the file name, title or text. Extra phrases per folder go in `[folders.aliases]`.
   - *Learned source:* every move you confirm is remembered with its Canvas course (`…/courses/12345`). Later downloads from that course point to the same folder.
   - *Model:* Claude Haiku (default) or the local model picks from the exact folder list (or NONE) via JSON-schema output. It sees each folder's course description from `[folders.descriptions]`, three example file names and your recent decisions. It must quote its evidence from the document; if the quote isn't really in the document, its confidence drops to low.
4. **Decision table** in `organizer/classifier.py::decide`. Two agreeing signals move automatically. Claude's own high confidence also moves automatically (`auto_move_on_llm_alone`); the local model alone only ever suggests.

If the model is unavailable (for example, offline), the organizer still uses course codes and learned sources, but asks before every move unless both agree.

## Files

- `config.toml`: folders, course descriptions, behaviour (the model is chosen on the command line, not here). Destinations are subfolders of `roots` matching `include_patterns`, plus `extra`, plus folders you created or picked through the app.
- `state/` (not tracked): `app.log`, `moves.jsonl` (undo log), `history.jsonl` (your decisions), `learned_folders.json`.
- `organizer/`: `watcher.py` detection · `motw.py` Mark of the Web · `extract.py` PDF text · `folders.py` destinations and course codes · `history.py` learning · `classifier.py` decision and prompt · `claude_client.py` / `ollama_client.py` models · `actions.py` move/undo/open · `notifier.py` + `ui.py` + `tray.py` interface · `app.py` wiring.

## Tests

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Future work is tracked in [docs/ROADMAP.md](docs/ROADMAP.md).
