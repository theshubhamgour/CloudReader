"""Extract ordered text blocks (headings + paragraphs) from manuscript files.

Extraction never rewrites prose. The only normalisation is whitespace inside a
paragraph and removal of Markdown syntax characters that are formatting, not text.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".docx", ".epub"}


class ManuscriptError(ValueError):
    """User-facing import error."""


@dataclass
class Block:
    text: str
    kind: str = "paragraph"  # paragraph | heading | title
    level: int = 0           # heading level (1 = top)


def _clean(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text.replace("\r", "")).strip()


def detect_format(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        if ext == ".pdf":
            raise ManuscriptError(
                "PDF import is not supported yet. Export the manuscript from your editor "
                "as DOCX, EPUB, Markdown or plain text and import that instead."
            )
        raise ManuscriptError(
            f"Unsupported file type '{ext or 'none'}'. Supported: DOCX, EPUB, TXT, Markdown."
        )
    if ext in (".docx", ".epub"):
        if not data.startswith(b"PK\x03\x04"):
            raise ManuscriptError(f"This file is not a valid {ext[1:].upper()} document (bad header).")
        try:
            zipfile.ZipFile(io.BytesIO(data)).testzip()
        except zipfile.BadZipFile as e:
            raise ManuscriptError(f"The {ext[1:].upper()} file is damaged: {e}") from e
        return ext[1:]
    if b"\x00" in data[:8192]:
        raise ManuscriptError("This file looks binary, not text. Is the extension correct?")
    return "md" if ext in (".md", ".markdown") else "txt"


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as e:
        raise ManuscriptError("Could not decode the text file. Save it as UTF-8 and try again.") from e


def extract_txt(text: str) -> list[Block]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    non_empty = [l for l in lines if l.strip()]
    blank_separated = text.count("\n\n") >= max(2, len(non_empty) // 8)
    if blank_separated:
        chunks = re.split(r"\n\s*\n", text)
        # Inside a chunk, single newlines are soft wraps; but a short first line
        # followed by more lines may be a heading glued to its paragraph.
        blocks = []
        for c in chunks:
            ls = [l.strip() for l in c.split("\n") if l.strip()]
            if not ls:
                continue
            blocks.append(Block(_clean(" ".join(ls))))
        return blocks
    return [Block(_clean(l)) for l in non_empty]


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _strip_md_inline(s: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)               # images
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)            # links
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)                  # bold
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)  # italics
    s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s


def extract_md(text: str) -> list[Block]:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)   # front matter
    blocks: list[Block] = []
    para: list[str] = []

    def flush():
        if para:
            t = _clean(_strip_md_inline(" ".join(para)))
            if t:
                blocks.append(Block(t))
            para.clear()

    for line in text.split("\n"):
        m = _MD_HEADING.match(line)
        if m:
            flush()
            blocks.append(Block(_clean(_strip_md_inline(m.group(2))), "heading", len(m.group(1))))
        elif not line.strip():
            flush()
        elif re.fullmatch(r"\s*([-*_]\s*){3,}", line):
            flush()
            blocks.append(Block("* * *"))
        else:
            para.append(re.sub(r"^\s*>\s?", "", line).strip())
    flush()
    return blocks


def extract_docx(data: bytes) -> list[Block]:
    import docx  # python-docx

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as e:  # python-docx raises many types for malformed files
        raise ManuscriptError(f"Could not read the DOCX file: {e}") from e
    blocks: list[Block] = []
    for p in doc.paragraphs:
        text = _clean(p.text)
        if not text:
            continue
        style = (p.style.name if p.style is not None else "") or ""
        if style == "Title":
            blocks.append(Block(text, "title", 0))
        elif m := re.match(r"Heading (\d)", style):
            blocks.append(Block(text, "heading", int(m.group(1))))
        else:
            blocks.append(Block(text))
    return blocks


def extract_epub(data: bytes) -> list[Block]:
    import warnings

    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    path = None
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as f:
            f.write(data)
            path = f.name
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = epub.read_epub(path, {"ignore_ncx": True})
    except Exception as e:
        raise ManuscriptError(f"Could not read the EPUB file: {e}") from e
    finally:
        if path:
            Path(path).unlink(missing_ok=True)

    blocks: list[Block] = []
    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "hr"]):
            if el.name == "hr":
                blocks.append(Block("* * *"))
                continue
            text = _clean(el.get_text(" "))
            if not text:
                continue
            if el.name.startswith("h"):
                blocks.append(Block(text, "heading", int(el.name[1])))
            else:
                blocks.append(Block(text))
    return blocks


def extract_blocks(filename: str, data: bytes) -> tuple[str, list[Block]]:
    if not data:
        raise ManuscriptError("The file is empty.")
    fmt = detect_format(filename, data)
    if fmt == "txt":
        blocks = extract_txt(decode_text(data))
    elif fmt == "md":
        blocks = extract_md(decode_text(data))
    elif fmt == "docx":
        blocks = extract_docx(data)
    else:
        blocks = extract_epub(data)
    if not any(b.text.strip() for b in blocks):
        raise ManuscriptError("No readable text was found in this manuscript.")
    return fmt, blocks
