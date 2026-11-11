"""Document cleaning — normalize whitespace, drop obvious noise."""

from __future__ import annotations

import re


def clean_text(text: str) -> str:
    # Normalize newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of spaces/tabs but keep paragraph breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Drop form-feed / null
    text = text.replace("\x00", "").replace("\x0c", "\n")
    # Soft hyphen cleanup
    text = text.replace("\u00ad", "")
    # De-hyphenate common line-break hyphenation: "exam-\nple" -> "example"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return text.strip()
