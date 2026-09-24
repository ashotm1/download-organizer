# Download Organizer

Download Organizer keeps your Downloads folder from turning into a pile of PDFs. It runs quietly in the Windows tray, and whenever your browser finishes downloading a PDF it reads the first page or two, asks an LLM which of your folders the file belongs in, and moves it there. If the model isn't sure, or nothing fits, the file stays where it is and you get a notification asking what to do.

It was built for course material (lecture slides, homework, assignments going into per-course folders), but it works for any set of folders you can describe in a sentence. It currently works on Windows only.

## How it works

The model needs enough context about your folders to decide well. For every destination folder it gets:

- a short description of what the folder is for, e.g. "CS 101 Intro to Programming, in Python: loops, functions, lists"
- a few example file names that already live there
- the files you've recently filed yourself, so it picks up your habits

Then it gets the downloaded document (file name, title, where it was downloaded from, and the first page of text) and has to pick exactly one folder from the list, or answer NONE. It also has to quote the words from the document that justify its choice. If the quote isn't actually in the document, the answer isn't trusted.

What happens next:

- **Confident match:** the file is moved, opened from its new place, and a notification shows up with an **Undo** button.
- **Not sure:** it stays in Downloads and you get "Move to X?" with **Move** / **Pick other** / **Leave**.
- **No match:** it's skipped and stays in Downloads. If the document mentions a course that has no folder yet (say "Biology 101"), it offers to create `bio101` and move it there.
- **Scanned PDF with no text:** you just get an alert that it wasn't sorted.

Anything you don't answer right away waits in **Review pending…** (double-click the tray icon). Nothing is ever deleted, and every move can be undone.

A few details worth knowing:

- **Only real downloads count.** The browser writes `file.pdf.crdownload` and renames it when the download finishes, and only that rename triggers the tool. PDFs you copy into Downloads yourself are left alone.
- **The PDF still opens.** After a move, the browser's own "Open file" link points to the old location, so the tool opens the file itself from wherever it ended up.
- Besides the model, it also notices course codes in the text (`CS 101`, `cs-101`, …) and remembers which Canvas course past downloads came from. These act as extra hints and a sanity check.

## LLM models

**Default: Claude Haiku**, called through the [Claude Code](https://claude.com/claude-code) command-line tool, so it runs on a normal Claude subscription with no API key. Each call is a small one-off request, about 5k tokens in and 1k out. The catch is that the first page of each PDF is sent to Anthropic.

**Fully local: [Ollama](https://ollama.com)**, with `--backend ollama` (uses `qwen2.5:3b` by default). Nothing leaves your machine. On a laptop's integrated GPU it answers in about 3 seconds. It's noticeably less reliable, though, so the local model never moves files on its own: it only suggests. A bigger local model (for example `qwen2.5:7b`) could do better, but that still needs testing.

For comparison, on a test set of 28 real PDFs (course material mixed with personal documents that should be left alone), Haiku got all 28 right. The best local 3B setup got 21, and several of its mistakes were confidently wrong.

There's no automatic fallback between the two. You choose with a flag when starting it:

```powershell
.venv\Scripts\pythonw.exe run.pyw                      # Claude Haiku
.venv\Scripts\pythonw.exe run.pyw --model sonnet       # another Claude model
.venv\Scripts\pythonw.exe run.pyw --backend ollama     # local model via Ollama
```

## Setup

```powershell
# settings: copy the example and fill in your folders and course descriptions
copy config.example.toml config.toml

# python environment (3.11+)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# for Claude: have the Claude Code VS Code extension installed (its claude.exe is found automatically)
# for the local option: install Ollama, then
ollama pull qwen2.5:3b

# check that your folders and the model are found
.venv\Scripts\python.exe -m organizer --check

# try it on one file without moving anything
.venv\Scripts\python.exe -m organizer --classify "path\to\some.pdf"

# run it (tray icon), and optionally start it at login
.venv\Scripts\pythonw.exe run.pyw
powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1
```

Tests: `.venv\Scripts\python.exe -m unittest discover -s tests -t .`

## Possible improvements

- **Cheaper Claude calls:** use the CLI's minimal `--bare` mode, reuse a cached base conversation that holds the folder info so each call only pays for the new document, and sort several downloads in one call when they arrive together.
- **Changing settings without a restart:** reload `config.toml` and the prompt automatically when they change.
- **Scanned PDFs:** read them with OCR or a vision model instead of just raising an alert.
- **Lighter background use:** run at below-normal priority so it never competes with whatever you're doing.
- **macOS and Linux support.**
