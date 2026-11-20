import pytest

from app.manuscript.chapters import detect_chapters
from app.manuscript.importers import ManuscriptError, extract_blocks
from app.processing.narration import Rule, prepare_tts_text
from app.processing.segmenter import segment_paragraphs, split_sentences
from app.services import library

from .conftest import SAMPLE_TXT, make_docx


def test_import_txt_detects_chapters_and_title(ctx):
    book = library.import_manuscript(ctx, "novel.txt", SAMPLE_TXT.encode())
    titles = [c["title"] for c in book["chapters"]]
    assert book["title"] == "Punching Through the Clouds" or "Front Matter" in titles
    assert "Chapter One: The Ascent" in titles
    assert "Chapter Two: Static" in titles
    assert book["word_count"] > 50


def test_txt_preserves_paragraph_boundaries(ctx):
    book = library.import_manuscript(ctx, "novel.txt", SAMPLE_TXT.encode())
    ch1 = next(c for c in book["chapters"] if c["title"].startswith("Chapter One"))
    paras = library.paragraphs_of(ctx.db.one("SELECT text FROM chapters WHERE id=?", (ch1["id"],))["text"])
    assert paras[0].startswith("Mara pressed her palm")
    assert paras[1] == '"We\'re above it now," Theo said. "Nothing can reach us here."'
    assert "* * *" in paras


def test_import_docx_uses_heading_styles(ctx):
    data = make_docx([
        ("Punching Through the Clouds", "Title"),
        ("The Ascent", "Heading 1"), ("First paragraph.", None), ("Second paragraph.", None),
        ("Static", "Heading 1"), ("Third paragraph.", None),
    ])
    book = library.import_manuscript(ctx, "novel.docx", data)
    assert book["title"] == "Punching Through the Clouds"
    assert [c["title"] for c in book["chapters"]] == ["The Ascent", "Static"]
    ch = ctx.db.one("SELECT text FROM chapters WHERE id=?", (book["chapters"][0]["id"],))
    assert ch["text"] == "First paragraph.\n\nSecond paragraph."


def test_original_manuscript_is_stored_unmodified(ctx):
    book = library.import_manuscript(ctx, "novel.txt", SAMPLE_TXT.encode())
    row = ctx.db.one("SELECT source_path FROM books WHERE id=?", (book["id"],))
    with open(row["source_path"], "rb") as f:
        assert f.read() == SAMPLE_TXT.encode()


def test_markdown_headings():
    md = b"# Book\n\n## Chapter 1\n\nHello *world*.\n\n## Chapter 2\n\nBye."
    _, blocks = extract_blocks("b.md", md)
    title, chapters = detect_chapters(blocks)
    assert title == "Book"
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2"]
    assert chapters[0].paragraphs == ["Hello world."]


@pytest.mark.parametrize("name,data,msg", [
    ("evil.exe", b"MZ....", "Unsupported"),
    ("book.pdf", b"%PDF-1.7", "PDF"),
    ("fake.docx", b"not a zip at all", "not a valid"),
    ("bin.txt", b"abc\x00\x00def", "binary"),
    ("empty.txt", b"", "empty"),
    ("blank.txt", b"   \n\n  ", "No readable text"),
])
def test_rejects_malformed_uploads(name, data, msg):
    with pytest.raises(ManuscriptError, match=msg):
        extract_blocks(name, data)


def test_upload_endpoint_rejects_bad_file_and_path_traversal(client):
    r = client.post("/api/books/import", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
    r = client.post("/api/books/import", files={"file": ("../../etc/passwd.txt", SAMPLE_TXT.encode(), "text/plain")})
    assert r.status_code == 200
    book_id = r.json()["id"]
    assert client.get(f"/api/books/{book_id}").json()["source_filename"] == "passwd.txt"


def test_segmentation_respects_limits_and_order():
    paras = [f"Paragraph {i}. " + "Words go here. " * 8 for i in range(12)]
    segs = segment_paragraphs(paras, target=300, max_chars=500)
    assert all(len(s.text) <= 500 for s in segs)
    joined = "\n\n".join(s.text for s in segs)
    assert joined == "\n\n".join(paras)  # nothing lost, order stable
    assert segs[0].paragraph_start == 0 and segs[-1].paragraph_end == 11


def test_long_paragraph_splits_on_sentences_not_inside_quotes():
    p = ('She said, "Stop. Wait. Listen to me." ' * 3) + "Then silence fell. " * 30
    segs = segment_paragraphs([p], target=200, max_chars=300)
    assert len(segs) > 1
    for s in segs:
        assert s.text.count('"') % 2 == 0, s.text
        assert len(s.text) <= 300


def test_sentence_split_keeps_dialogue_together():
    parts = split_sentences('“Run. Now. Go!” he said. She ran.')
    assert parts == ['“Run. Now. Go!” he said.', 'She ran.']


def test_pronunciation_mapping_never_touches_source():
    src = "Aeryn met aeryn at the Vael gate. <not a tag>"
    tts, repl = prepare_tts_text(src, [Rule("Aeryn", "AIR-in"), Rule("Vael", "Vale", True)], supports_tags=True)
    assert tts == "AIR-in met AIR-in at the Vale gate. (not a tag)"
    for r in repl:
        assert src[r["source_start"]:r["source_end"]] == r["original"]
        assert tts[r["tts_start"]:r["tts_end"]] == r["spoken"]


def test_chapter_split_merge_rename_reorder(ctx):
    book = library.import_manuscript(ctx, "novel.txt", SAMPLE_TXT.encode())
    ch = next(c for c in book["chapters"] if c["title"].startswith("Chapter One"))
    new_id = library.split_chapter(ctx, ch["id"], 2, "Part B")
    titles = [c["title"] for c in library.get_book(ctx, book["id"])["chapters"]]
    assert titles[titles.index(ch["title"]) + 1] == "Part B"
    library.merge_with_next(ctx, ch["id"])
    assert not ctx.db.one("SELECT id FROM chapters WHERE id=?", (new_id,))
    library.rename_chapter(ctx, ch["id"], "Renamed")
    ids = [c["id"] for c in library.get_book(ctx, book["id"])["chapters"]]
    library.reorder_chapters(ctx, book["id"], list(reversed(ids)))
    assert [c["id"] for c in library.get_book(ctx, book["id"])["chapters"]] == list(reversed(ids))


def test_document_without_headings_is_one_full_text_part():
    _, blocks = extract_blocks("notes.txt", b"Just a note.\n\nAnother paragraph with no chapter headings.")
    _, chapters = detect_chapters(blocks)
    assert [c.title for c in chapters] == ["Full Text"]
    assert len(chapters[0].paragraphs) == 2


def test_readable_title_from_file_name():
    assert library.title_from_filename("github-support_contributors-request") == "Github Support Contributors Request"
    assert library.title_from_filename("My_Novel-Draft") == "My Novel Draft"


def test_title_line_at_top_of_text_file_is_not_a_chapter():
    txt = b"The Lighthouse Keeper\n\nChapter One: Dusk\n\nElias climbed the steps.\n\nChapter Two: Fog\n\nA horn sounded."
    _, blocks = extract_blocks("keeper.txt", txt)
    title, chapters = detect_chapters(blocks)
    assert title == "The Lighthouse Keeper"
    assert [c.title for c in chapters] == ["Chapter One: Dusk", "Chapter Two: Fog"]


def test_real_front_matter_is_kept():
    txt = b"A note before we begin.\n\nThis book was written over many winters.\n\nChapter One: Dusk\n\nElias climbed the steps."
    _, blocks = extract_blocks("keeper.txt", txt)
    _, chapters = detect_chapters(blocks)
    assert chapters[0].title == "Front Matter" and len(chapters[0].paragraphs) == 2
