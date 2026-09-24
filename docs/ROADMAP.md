# Roadmap

Deferred on purpose; roughly in priority order.

## Claude (Haiku) as the classifier, and making each call cheaper
**Why:** in the 2026-09-23 evaluation (28 PDFs from the course folders plus personal and other-course documents), Haiku called through Claude Code on the user's Pro subscription got 28/28 with no confident mistakes. The best qwen2.5:3b prompt got 21/28, with 7 wrong answers marked "high". Median time was 8.7 s per file. The trade-off: each PDF's first-page text goes to Anthropic and uses a little of the plan's usage limit.

**How it's called:** `claude.exe -p --model haiku --tools "" --no-session-persistence --output-format json --system-prompt <prompt> --json-schema <schema>`. The answer is in `structured_output` and the tokens in `usage`. The binary ships with the VS Code extension (`...\anthropic.claude-code-<version>\resources\native-binary\claude.exe`); the path changes with each extension update.

**Measured cost per PDF:** ~5,000 input tokens (about 3,700 are Claude Code's own built-in instructions) + ~1,000 output tokens (including Haiku's thinking). That's about a quarter to a sixth of one short message in a long Opus chat. Every call is a fresh one-off session, so nothing is reused from the cache.

**Optimizations to try, measuring tokens per file on the same 28-file set:**
1. `--bare`: drops most of Claude Code's own overhead on every call. Simplest win.
2. **Branch from a base session:** create a base session with the instructions and folder list once, then run each PDF as `--resume <base> --fork-session`. The shared start is read from the cache at ~0.1× weight and branches never see each other's documents. It only pays off while the cache is alive (5 minutes or 1 hour); a lone download after that pays the full write again. Never use one growing chat: every PDF would re-read all earlier ones.
3. **Batching:** when several downloads finish within seconds, classify them in one call so they share the overhead.
4. Less or no thinking for Haiku, and less document text (1,000 instead of 2,000 characters).
5. Keep qwen as the offline fallback.

**Cache lifetime, which also applies to chats with Claude Code itself:** a cached conversation lives 60 minutes (1-hour cache) after the last message. Within that window it is re-read at ~0.1× input weight; after it expires, the next message rewrites the whole history at 2× weight. For a ~270k-token chat that's roughly 40× more for the first message after a break. Long chats: continue within the hour, or start a new chat.

## Scanned PDFs (no text layer)
Today they only raise a "Not sorted" alert. Options when this matters:
- OCR the first page with Tesseract (`pymupdf` can call it via `page.get_textpage_ocr()` once Tesseract is installed), then run the normal pipeline.
- Or send a rendered image of page 1 to a vision model in Ollama (`qwen2.5vl:3b`, `llama3.2-vision`). Slow on CPU-only machines.

## Subfolders inside a course
Files go to the course folder's top level. Could pick among existing subfolders (`HW`, `project2`, `lectures`) with a second, narrower classification step.

## Other file types
`detection.extensions` accepts more than `.pdf`, but extraction is PDF-only. Candidates: `.docx` (python-docx), `.pptx` (python-pptx), `.zip` (file listing), images (vision model).

## Duplicates
Detect an identical file (same hash) already in the destination and offer to skip instead of saving `name (1).pdf`.

## Calibration
- Use token log-probabilities for the model's folder choice (if the Ollama version exposes them) instead of its self-reported confidence.
- Track how often each tier's decision is undone or changed; tighten or relax the auto-move rule from that data.

## Files downloaded while the app was not running
Currently ignored. Could offer a one-time review of recent PDFs in Downloads that carry a Mark of the Web at startup.

## Browser extension
A small Edge extension using `chrome.downloads` would report downloads exactly (URL, tab, referrer) and could even update Edge's own download entry. Only worth it if Mark-of-the-Web detection proves insufficient.
