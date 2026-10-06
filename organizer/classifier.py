"""Combines course-code rules, learned sources and the local model into one decision."""
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import folders as fl
from .config import Config
from .folders import Folder
from .history import History
from .claude_client import ClaudeCode
from .ollama_client import LlmError, Ollama

log = logging.getLogger(__name__)

AUTO, ASK, NO_MATCH = "auto", "ask", "no_match"
NONE = "NONE"
EXAMPLES_WITH_DESCRIPTION = 3

SYSTEM_PROMPT = """You file a university student's downloaded PDFs into their course folders.

Rules:
1. Choose a folder only if the document clearly matches that folder's course description.
2. If the document names a course that is not in the folder list (for example "Physics 182" or
   "PHIL 100"), answer NONE and set new_folder_name to that course in the folders' style (phys182).
3. Personal and administrative documents (forms, IDs, resumes, receipts, legal, financial or
   employment papers) are always NONE, with an empty new_folder_name.
4. If nothing clearly matches, answer NONE. Prefer NONE over a guess.
5. reason: a few words on what the document is about and why it fits the folder you chose (or
   none). It is shown to the student so they can check your choice at a glance.

Examples (the folders here are made up):
- "Biology 101 Lab 3: Cell Division" -> folder NONE, new_folder_name "bio101",
  reason "Biology 101 lab on cell division; no biology folder"
- "Form W-4 Employee's Withholding Certificate" -> folder NONE, new_folder_name "",
  reason "US tax withholding form, not course material"
- "Homework 2: implement a linked list in C", with a folder described as "Programming in C" -> that folder,
  reason "homework on linked lists in C, matches Programming in C"
"""

@dataclass
class DocInfo:
    filename: str
    text: str
    title: str
    source_key: str | None
    source_url: str | None


@dataclass
class LlmResult:
    folder: str  # a folder key or NONE
    confidence: str
    reason: str
    new_folder_name: str
    backend: str = ""
    trusted: bool = False  # whether this backend may auto-move on its own confidence


@dataclass
class Decision:
    tier: str
    folder: Folder | None
    reason: str
    suggested_new: str | None = None
    signals: dict = field(default_factory=dict)


def decide(rule: str | None, source: str | None, llm: LlmResult | None,
           auto_on_llm_alone: bool) -> tuple[str, str | None, str]:
    """Pure decision table over folder keys. Returns (tier, folder_key, reason)."""
    llm_folder = llm.folder if llm and llm.folder != NONE else None
    if rule and source and rule != source:
        # Two strong signals disagree: let the model break the tie, but always ask.
        pick = llm_folder if llm_folder in (rule, source) else rule
        return ASK, pick, f"course code says {rule}, past downloads from this source went to {source}"
    strong = rule or source
    both = rule is not None and source is not None
    if strong:
        what = "course code and past downloads from this source" if both else (
            "course code in the document" if rule else "past downloads from this source")
        if llm_folder == strong:
            return AUTO, strong, f"{what}; the model agrees"
        if both:
            return AUTO, strong, what
        if llm is None:
            return ASK, strong, f"{what} (model unavailable)"
        disagreement = f"the model suggested {llm_folder}" if llm_folder else "the model found no match"
        return ASK, strong, f"{what}, but {disagreement}"
    if llm_folder:
        if llm.confidence == "high" and auto_on_llm_alone:
            return AUTO, llm_folder, f"model: {llm.reason}"
        return ASK, llm_folder, f"model ({llm.confidence}): {llm.reason}"
    return NO_MATCH, None, (f"model: {llm.reason}" if llm else "no course code or known source")


DEFAULT_MODELS = {"claude": "haiku", "ollama": "qwen2.5:3b"}


def build_llm(cfg: Config):
    """The one model the organizer uses, chosen by the --backend/--model command-line flags."""
    model = cfg.model or DEFAULT_MODELS[cfg.backend]
    if cfg.backend == "claude":
        return ClaudeCode(model, cfg.claude_exe, cfg.claude_timeout_s)
    return Ollama(cfg.ollama_url, model, cfg.ollama_timeout_s, cfg.keep_alive, cfg.num_ctx)


class Classifier:
    def __init__(self, cfg: Config, llm, history: History):
        self.cfg, self.llm, self.history = cfg, llm, history

    def _prompt(self, folders: list[Folder], doc: DocInfo) -> str:
        lines = ["Folders:"]
        for f in folders:
            # With a description, a few file names are enough; without one they are all the model has.
            samples = f.samples[:EXAMPLES_WITH_DESCRIPTION] if f.description else f.samples
            examples = f"e.g. {', '.join(samples)}" if samples else "empty"
            about = f"{f.description} " if f.description else ""
            lines.append(f"- {f.key}: {about}({examples})")
        known = {f.key for f in folders}
        examples = []
        for r in self.history.examples():
            folder = fl.find(folders, r["folder"])
            if folder and folder.key in known:
                src = f" from {r['source_url']}" if r.get("source_url") else ""
                examples.append(f"- \"{r['file']}\"{src} -> {folder.key}")
        if examples:
            lines += ["", "Recently filed by the user:", *examples]
        lines += [
            "",
            "Document:",
            f"File name: {doc.filename}",
            f"Downloaded from: {doc.source_url or 'unknown'}",
            f"PDF title: {doc.title or 'none'}",
            "First page text:",
            '"""',
            doc.text,
            '"""',
        ]
        return "\n".join(lines)

    def ask_llm(self, folders: list[Folder], doc: DocInfo) -> LlmResult | None:
        schema = {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "folder": {"type": "string", "enum": [f.key for f in folders] + [NONE]},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "new_folder_name": {"type": "string"},
            },
            "required": ["reason", "folder", "confidence", "new_folder_name"],
        }
        llm = self.llm
        try:
            out = llm.chat_json(SYSTEM_PROMPT, self._prompt(folders, doc), schema)
        except LlmError as e:
            log.warning("%s unavailable, deciding without it: %s", llm.name, e)
            return None
        keys = {f.key for f in folders}
        folder = out.get("folder") if out.get("folder") in keys else NONE
        confidence = out.get("confidence") if out.get("confidence") in ("high", "medium", "low") else "low"
        reason = str(out.get("reason", "")).strip()
        return LlmResult(folder, confidence, reason, str(out.get("new_folder_name", "")), llm.name, llm.trusted)

    def classify(self, folders: list[Folder], doc: DocInfo) -> Decision:
        scores = fl.score(folders, doc.filename, doc.title, doc.text)
        rule = fl.rule_winner(scores)
        learned = fl.find(folders, self.history.source_folder(doc.source_key))
        source = learned.key if learned else None
        # Two agreeing strong signals decide on their own; skip the slow CPU model call.
        llm = None if (rule and rule == source) or not folders else self.ask_llm(folders, doc)
        tier, key, reason = decide(rule, source, llm, self.cfg.auto_move_on_llm_alone and bool(llm and llm.trusted))
        suggested = None
        if tier == NO_MATCH:
            suggested = fl.unknown_course_code(folders, doc.filename, doc.text) or \
                fl.sanitize_folder_name(llm.new_folder_name if llm else None)
        signals = {"scores": scores, "rule": rule, "source": source,
                   "llm": llm.__dict__ if llm else None}
        log.info("%s -> %s %s (%s) signals=%s", doc.filename, tier, key, reason, signals)
        return Decision(tier, next((f for f in folders if f.key == key), None), reason, suggested, signals)


def suggested_parent(cfg: Config) -> Path | None:
    return cfg.roots[0] if cfg.roots else None
