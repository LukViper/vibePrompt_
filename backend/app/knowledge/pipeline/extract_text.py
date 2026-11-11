"""Text extraction from PDF/EPUB/TXT/DOCX."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass
class ExtractionResult:
    text: str
    pages: list[str]
    warnings: list[str]
    method: str


def extract_text(path: Path, mime_type: str | None = None) -> ExtractionResult:
    ext = path.suffix.lower()
    if ext == ".txt" or (mime_type or "").startswith("text/plain"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        return ExtractionResult(text=raw, pages=[raw], warnings=[], method="txt")
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".epub":
        return _extract_epub(path)
    raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(path: Path) -> ExtractionResult:
    warnings: list[str] = []
    # Prefer pypdf (lighter); fall back to pymupdf if present.
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n\n".join(pages)
        if not text.strip():
            warnings.append("PDF text layer empty — may be scanned/image-only")
        return ExtractionResult(text=text, pages=pages, warnings=warnings, method="pypdf")
    except ImportError:
        warnings.append("pypdf not installed")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"pypdf failed: {exc}")

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        doc.close()
        text = "\n\n".join(pages)
        return ExtractionResult(text=text, pages=pages, warnings=warnings, method="pymupdf")
    except ImportError:
        warnings.append("pymupdf not installed")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"pymupdf failed: {exc}")

    raise ValueError("PDF extraction unavailable: " + "; ".join(warnings))


def _extract_docx(path: Path) -> ExtractionResult:
    warnings: list[str] = []
    try:
        import docx  # python-docx

        document = docx.Document(str(path))
        paras = [p.text for p in document.paragraphs if p.text.strip()]
        text = "\n\n".join(paras)
        return ExtractionResult(text=text, pages=[text], warnings=warnings, method="python-docx")
    except ImportError:
        warnings.append("python-docx not installed; using zip/xml fallback")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"python-docx failed: {exc}")

    # Minimal OOXML fallback
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        texts = [t.text for t in root.findall(".//w:t", ns) if t.text]
        text = "\n".join(texts)
        return ExtractionResult(text=text, pages=[text], warnings=warnings, method="docx-zip")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"DOCX extraction failed: {exc}; " + "; ".join(warnings)) from exc


def _extract_epub(path: Path) -> ExtractionResult:
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
            names.sort()
            pages: list[str] = []
            for name in names:
                raw = zf.read(name).decode("utf-8", errors="replace")
                pages.append(_strip_html(raw))
            text = "\n\n".join(pages)
            if not text.strip():
                warnings.append("EPUB produced empty text")
            return ExtractionResult(text=text, pages=pages, warnings=warnings, method="epub-zip")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"EPUB extraction failed: {exc}") from exc


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&lt;", "<", html)
    html = re.sub(r"&gt;", ">", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()
