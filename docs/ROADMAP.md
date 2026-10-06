# Roadmap

Deferred on purpose; roughly in priority order.

## Claude (Haiku) as the classifier, and making each call cheaper
**Why:** in the 2026-09-23 evaluation (28 PDFs from the course folders plus personal and other-course documents), Haiku called through Claude Code on the user's Pro subscription got 28/28 with no confident mistakes. The best qwen2.5:3b prompt got 21/28, with 7 wrong answers marked "high". Median time was 8.7 s per file. The trade-off: each PDF's first-page text goes to Anthropic and uses a little of the plan's usage limit.

**How it's called:** `claude.exe -p --model haiku --tools "" --no-session-persistence --strict-mcp-config --output-format json --system-prompt <prompt> --json-schema <schema>`. The answer is in `structured_output`; total usage across all turns of the call is in `modelUsage` (`usage` alone is only the last turn). The binary ships with the VS Code extension (`...\anthropic.claude-code-<version>\resources\native-binary\claude.exe`); the path changes with each extension update. Every call now logs its own `tokens in/cache_read/cache_write/out/turns/api_ms/cost` line to `app.log` (added 2026-09-28) — no more reconstructing usage from timing after the fact.

**2026-09-28 findings (proxy-captured real traffic), superseding the numbers below:**
- The account's claude.ai connectors (Google Drive, Claude Docs — ~20 tools) were loading into every call by default, ~6,600 tokens of it, unasked for and unused. `--strict-mcp-config` removes them: first-turn input dropped from ~7,965 to ~1,300 tokens. Also closed a real exposure — `trash_file`/`share_file` were reachable before this flag (blocked only by print-mode's permission denial, not by absence).
- Re-ran accuracy after the flag change against 33 real course PDFs (superset of, not identical to, the original 28-file set — didn't include personal/admin docs this time): 32/33 as scored, but the one "miss" (`GradStudyPath.pdf` → NONE, high confidence) was right: the user confirmed it isn't course material and it has been moved out of the course folder. So 33/33.
- With `--json-schema`, the model almost always free-texts on turn 1, gets the CLI's `[structured-output-enforce]` nudge, then calls the tool on turn 2 — a second full request every time. But turn 2's input is mostly cache-read (0.1x) of turn 1's own content, since it's the same in-process conversation just resent — `--no-session-persistence` only stops the transcript being *saved*, it doesn't affect this in-call caching. So eliminating turn 2 (e.g. a stricter system prompt) would save roughly 15–20% of total call cost, not ~50%.
- `--effort <low|medium|high|xhigh|max>` is the only thinking-control lever the CLI exposes (no direct on/off flag). Tested on an easy, obvious-match file: any explicit level cut cost 40–60% vs. leaving it unset (unset defaults close to max thinking budget). But effort is a *ceiling*, not a target — on an easy task the model's natural thinking length is short regardless of which explicit level is set, so low/medium/high weren't cleanly ordered against each other (single sample each, task wasn't hard enough to make any of them bind). The reliable win is "set `--effort` explicitly, at any level" vs. leaving it unset; which level matters is untested and would only show up on genuinely hard/ambiguous files. Superseded on 2026-10-05: thinking is now off entirely (see below).

**2026-10-05: thinking off, and `reason` instead of a checked quote:**
- Thinking can be switched off completely after all: `--settings '{"alwaysThinkingEnabled": false}'` (also `CLAUDE_CODE_DISABLE_THINKING=1` or `MAX_THINKING_TOKENS=0`; all three gave 0 thinking tokens). The app now passes the `--settings` flag. On the course-PDF suite: 37/37 correct, median 3.3 s per file (was 7.1 s with thinking), slowest 5.8 s (was 16.8 s). Thinking had been ~80% of each call's time; CLI start and exit add only ~1.2 s.
- Timed with stream events, each call was one API request (thinking, a short text, then the structured-output tool call in the same message). `num_turns: 2` counts the local tool result, not a second request, so the "turn 2" described above didn't happen in these runs.
- The `evidence` quote check (at least 80% of the quoted words had to appear in the document, otherwise confidence dropped to low) was removed. Without thinking, Haiku wrote descriptive evidence ("cs101 HW4 hashing, trees, graphs, topological sort") for 3 correctly filed documents, and the check turned them into "ask". In every Haiku run its downgrades were false alarms, it never checks whether the folder is right, and it only affects Claude (the only backend allowed to auto-move). It was written against qwen inventing things. The model now returns a short `reason` (what the document is about and why it fits), shown in notifications and saved in `history.jsonl` for review.
- Not yet tested without thinking: personal/administrative and other-course documents (the eval suite only has course folders).

**Optimizations to try, measuring tokens per file on the same file set:**
1. `--bare`: drops most of Claude Code's own overhead on every call. Simplest win, not yet tested.
2. **Branch from a base session:** create a base session with the instructions and folder list once, then run each PDF as `--resume <base> --fork-session`. The shared start is read from the cache at ~0.1× weight and branches never see each other's documents. It only pays off while the cache is alive (5 minutes, or 1 hour — Claude Code's default turned out to be the 1-hour/2x-write tier, confirmed 2026-09-28); a lone download after that pays the full write again. Never use one growing chat: every PDF would re-read all earlier ones.
3. **Batching:** when several downloads finish within seconds, classify them in one call so they share the overhead.
4. ~~Less or no thinking for Haiku~~ → done 2026-10-05, thinking is off (see above). Less document text (1,000 instead of 2,000 characters) is still untested.
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
