"""Text and metadata extraction from the first pages of a PDF."""
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class Extracted:
    text: str = ""
    title: str = ""
    author: str = ""
    subject: str = ""
    page_count: int = 0
    error: str | None = None

    def has_text(self, min_chars: int) -> bool:
        return sum(c.isalnum() for c in self.text) >= min_chars


def _normalize(text: str) -> str:
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def extract(path: Path, pages: int, max_chars: int) -> Extracted:
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # corrupt or not really a PDF
        return Extracted(error=f"could not open: {e}")
    with doc:
        if doc.needs_pass:
            return Extracted(page_count=doc.page_count, error="password-protected")
        meta = doc.metadata or {}
        parts = []
        try:
            for i in range(min(pages, doc.page_count)):
                parts.append(doc[i].get_text("text"))
        except Exception as e:
            return Extracted(page_count=doc.page_count, error=f"could not read text: {e}")
        return Extracted(
            text=_normalize("\n".join(parts))[:max_chars],
            title=(meta.get("title") or "").strip(),
            author=(meta.get("author") or "").strip(),
            subject=(meta.get("subject") or "").strip(),
            page_count=doc.page_count,
        )
