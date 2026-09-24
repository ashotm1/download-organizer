"""Destination folders: discovery, short profiles for the model, and course-code matching."""
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

# Department spellings that should count as the same course code.
DEPT_SYNONYMS = {
    "cs": ["cs", "compsci", "cmpsci", "comp sci"],
    "ger": ["ger", "german"],
}
_CODE_NAME = re.compile(r"^([A-Za-z]{2,8})[\s_-]?(\d{2,4})$")
# Uppercase "ABC 123" in document text; the filename is matched case-insensitively.
_GENERIC_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,5}) ?[-_]?(\d{3})(?![0-9])")
_GENERIC_CODE_ANYCASE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,5})[ _-]?(\d{3})(?![0-9])")
_NOT_COURSES = {
    "isbn", "issn", "page", "pg", "room", "rm", "suite", "box", "no", "tel", "fax", "zip", "usd",
    "eur", "doi", "id", "po", "us", "utc", "est", "edt", "gmt", "apt", "ch", "vol", "sec", "fig",
    "ext", "ref", "order", "hw", "lab", "pa", "ps", "ex", "lec", "img", "scan", "dsc", "screenshot",
}
_SKIP_DIRS = {".git", ".vs", ".vscode", "__pycache__", "node_modules", "venv", ".venv", "__MACOSX"}
_DOC_EXTS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".txt", ".md", ".epub"}
SAMPLES_PER_FOLDER = 8


@dataclass
class Folder:
    key: str
    path: Path
    description: str = ""
    samples: list[str] = field(default_factory=list)
    patterns: list[re.Pattern] = field(default_factory=list)


def _phrase(text: str) -> str:
    return r"\s*".join(re.escape(part) for part in text.split())


def code_patterns(name: str, aliases: list[str]) -> list[re.Pattern]:
    pats = []
    m = _CODE_NAME.match(name)
    if m:
        dept, num = m.group(1).lower(), m.group(2)
        depts = "|".join(_phrase(d) for d in DEPT_SYNONYMS.get(dept, [dept]))
        pats.append(re.compile(rf"(?<![A-Za-z0-9])(?:{depts})\s*[-_.]?\s*{num}(?![0-9])", re.I))
    for alias in aliases:
        pats.append(re.compile(rf"(?<![A-Za-z0-9]){_phrase(alias)}(?![A-Za-z0-9])", re.I))
    return pats


def _sample_files(folder: Path, limit: int = SAMPLES_PER_FOLDER) -> list[str]:
    """Most recent document names inside a folder (two levels deep), without hydrating OneDrive files."""
    found: list[tuple[bool, float, str]] = []
    stack = [(folder, 0)]
    while stack and len(found) < 400:
        current, depth = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith((".", "~$", "#")):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth < 1 and e.name not in _SKIP_DIRS:
                        stack.append((Path(e.path), depth + 1))
                else:
                    is_doc = os.path.splitext(e.name)[1].lower() in _DOC_EXTS
                    found.append((is_doc, e.stat(follow_symlinks=False).st_mtime, e.name))
            except OSError:
                continue
    found.sort(key=lambda t: (t[0], t[1]), reverse=True)
    names, seen = [], set()
    for _, _, name in found:
        if name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
        if len(names) >= limit:
            break
    return names


def discover(cfg: Config, learned: list[Path]) -> list[Folder]:
    include = [re.compile(p, re.I) for p in cfg.include_patterns]
    candidates: list[Path] = []
    for root in cfg.roots:
        try:
            subdirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
        except OSError as e:
            log.warning("cannot list root %s: %s", root, e)
            continue
        candidates += [p for p in subdirs if any(r.search(p.name) for r in include)]
    candidates += [p for p in [*cfg.extra_folders, *learned] if p.is_dir()]

    folders: list[Folder] = []
    seen_paths, seen_keys = set(), set()
    for path in candidates:
        norm = os.path.normcase(str(path.resolve()))
        if norm in seen_paths:
            continue
        seen_paths.add(norm)
        key = path.name if path.name.lower() not in seen_keys else f"{path.parent.name}/{path.name}"
        seen_keys.add(key.lower())
        folders.append(Folder(
            key=key,
            path=path,
            description=cfg.descriptions.get(path.name.lower(), ""),
            samples=_sample_files(path),
            patterns=code_patterns(path.name, cfg.aliases.get(path.name.lower(), [])),
        ))
    return folders


def find(folders: list[Folder], path: Path | str | None) -> Folder | None:
    if path is None:
        return None
    norm = os.path.normcase(str(Path(path).resolve()))
    return next((f for f in folders if os.path.normcase(str(f.path.resolve())) == norm), None)


def score(folders: list[Folder], filename: str, title: str, text: str) -> dict[str, float]:
    """Weighted course-code hits per folder key. The filename and PDF title weigh more than body text."""
    scores: dict[str, float] = {}
    for f in folders:
        s = 0.0
        for pat in f.patterns:
            s += 3 * len(pat.findall(filename)) + 2 * len(pat.findall(title)) + len(pat.findall(text))
        if s:
            scores[f.key] = s
    return scores


def rule_winner(scores: dict[str, float]) -> str | None:
    """The folder whose code clearly dominates: present, and at least twice the runner-up."""
    if not scores:
        return None
    ranked = sorted(scores.values(), reverse=True)
    top_key = max(scores, key=scores.get)
    if len(ranked) == 1 or ranked[0] >= 2 * ranked[1]:
        return top_key
    return None


def unknown_course_code(folders: list[Folder], filename: str, text: str) -> str | None:
    """A course code in the document that has no folder yet, formatted like existing folders (cs285)."""
    counts: Counter[str] = Counter()
    for pattern, source, weight in ((_GENERIC_CODE_ANYCASE, filename, 3), (_GENERIC_CODE, text, 1)):
        for dept, num in pattern.findall(source):
            if dept.lower() not in _NOT_COURSES:
                counts[f"{dept.lower()}{num}"] += weight
    for code in list(counts):
        if any(p.search(code) for f in folders for p in f.patterns):
            del counts[code]
    return counts.most_common(1)[0][0] if counts else None


_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_folder_name(name: str | None) -> str | None:
    if not name:
        return None
    name = _INVALID_NAME.sub("", name).strip().strip(".").strip()
    return name[:60] or None
