"""What counts as a resume file (security.md > File Upload Handling).

The type is decided from the bytes, never from the filename or the type the browser claims. These
tests need no server: they feed the rules bytes directly.
"""

import io
import zipfile

import pytest

from app.services.resume_files import (
    DOCX_TYPE,
    MAX_RESUME_BYTES,
    MAX_ZIP_ENTRIES,
    PDF_TYPE,
    clean_filename,
    content_disposition,
    detect_resume_type,
)


def make_docx(extra_entries: int = 0, with_document: bool = True, with_types: bool = True) -> bytes:
    """A minimal Word file: a ZIP with the two parts every .docx has."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if with_types:
            archive.writestr("[Content_Types].xml", "<Types/>")
        if with_document:
            archive.writestr("word/document.xml", "<document/>")
        for number in range(extra_entries):
            archive.writestr(f"word/extra{number}.xml", "x")
    return buffer.getvalue()


MINIMAL_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


# ---- telling the types apart --------------------------------------------------------------


def test_a_pdf_is_recognised() -> None:
    assert detect_resume_type(MINIMAL_PDF) == PDF_TYPE


@pytest.mark.parametrize("version", ["1.0", "1.4", "1.7", "2.0"])
def test_pdf_versions_are_recognised(version: str) -> None:
    assert detect_resume_type(f"%PDF-{version}\n".encode() + b"rest") == PDF_TYPE


def test_a_word_file_is_recognised() -> None:
    assert detect_resume_type(make_docx()) == DOCX_TYPE


@pytest.mark.parametrize(
    ("label", "data"),
    [
        ("nothing at all", b""),
        ("plain text", b"My resume\nI am great.\n"),
        ("a PNG image", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50),
        ("a Windows program", b"MZ\x90\x00" + b"\x00" * 100),
        ("a Linux program", b"\x7fELF" + b"\x00" * 100),
        ("a web page", b"<html><script>alert(1)</script></html>"),
        ("a script", b"#!/bin/sh\nrm -rf /\n"),
        ("only the start of a PDF header", b"%PDF"),
        ("a PDF header with no version", b"%PDF-\n"),
        ("a PDF header not at the start", b"junk%PDF-1.7\n"),
        ("a PDF header after a blank line", b"\n%PDF-1.7\n"),
        ("random bytes", bytes(range(256)) * 4),
    ],
)
def test_other_things_are_refused(label: str, data: bytes) -> None:
    assert detect_resume_type(data) is None, label


def test_a_zip_that_is_not_a_word_file_is_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")
        archive.writestr("run.exe", "MZ")

    assert detect_resume_type(buffer.getvalue()) is None


@pytest.mark.parametrize("missing", ["document", "content types"])
def test_a_zip_missing_a_required_word_part_is_refused(missing: str) -> None:
    data = make_docx(with_document=missing != "document", with_types=missing != "content types")

    assert detect_resume_type(data) is None


def test_a_truncated_zip_is_refused() -> None:
    data = make_docx()

    assert detect_resume_type(data[: len(data) // 2]) is None


def test_a_zip_with_a_corrupted_directory_is_refused() -> None:
    data = bytearray(make_docx())
    data[-10:] = b"\x00" * 10  # the central directory's end record

    assert detect_resume_type(bytes(data)) is None


def test_a_zip_with_an_absurd_number_of_entries_is_refused() -> None:
    # A real resume has a handful of parts. Only the list of names is ever read, never the content.
    assert detect_resume_type(make_docx(extra_entries=MAX_ZIP_ENTRIES + 1)) is None


def test_a_word_file_with_many_but_allowed_entries_is_accepted() -> None:
    assert detect_resume_type(make_docx(extra_entries=100)) == DOCX_TYPE


def test_the_size_limit_is_five_megabytes() -> None:
    assert MAX_RESUME_BYTES == 5 * 1024 * 1024


# ---- the name shown for the file ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "content_type", "expected"),
    [
        ("cv.pdf", PDF_TYPE, "cv.pdf"),
        ("My CV.PDF", PDF_TYPE, "My CV.PDF"),
        ("cv.docx", DOCX_TYPE, "cv.docx"),
        # The name never decides the type, so a missing or wrong extension is corrected.
        ("cv", PDF_TYPE, "cv.pdf"),
        ("cv.exe", PDF_TYPE, "cv.exe.pdf"),
        ("cv.pdf", DOCX_TYPE, "cv.pdf.docx"),
        ("cv.doc", DOCX_TYPE, "cv.doc.docx"),
    ],
)
def test_the_extension_always_matches_what_the_file_really_is(
    raw: str, content_type: str, expected: str
) -> None:
    assert clean_filename(raw, content_type) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\windows\\system32\\cv.pdf", "cv.pdf"),
        ("/absolute/path/cv.pdf", "cv.pdf"),
        ("C:\\Users\\me\\cv.pdf", "cv.pdf"),
        ("line\nbreak\r\ncv.pdf", "linebreakcv.pdf"),
        ("tab\there.pdf", "tabhere.pdf"),
        ("nul\x00byte.pdf", "nulbyte.pdf"),
        ("  spaced name .pdf  ", "spaced name .pdf"),
        ("résumé.pdf", "résumé.pdf"),
    ],
)
def test_the_name_is_reduced_to_a_plain_file_name(raw: str, expected: str) -> None:
    assert clean_filename(raw, PDF_TYPE) == expected


def test_characters_that_reorder_text_are_removed_so_an_extension_cannot_be_disguised() -> None:
    # "cv\u202efdp.exe" would be shown as "cvexe.pdf" by a browser that obeys the control character.
    name = clean_filename("cv\u202efdp.exe", PDF_TYPE)

    assert "\u202e" not in name and name == "cvfdp.exe.pdf"


@pytest.mark.parametrize("raw", ["", "   ", "..", ".", "/", "\x00\x01", "../"])
def test_a_missing_or_meaningless_name_becomes_resume(raw: str) -> None:
    assert clean_filename(raw, PDF_TYPE) == "resume.pdf"


def test_markup_in_a_name_is_kept_as_text_not_changed() -> None:
    # Escaping is the job of whoever shows it (React does); changing it here would hide the truth.
    assert clean_filename("<img src=x onerror=alert(1)>.pdf", PDF_TYPE) == (
        "<img src=x onerror=alert(1)>.pdf"
    )


def test_a_very_long_name_is_shortened_but_keeps_its_extension() -> None:
    name = clean_filename("a" * 400 + ".pdf", PDF_TYPE)

    assert len(name) <= 255
    assert name.endswith(".pdf")


# ---- the download header ------------------------------------------------------------------


def test_the_download_header_asks_for_a_download_with_the_name() -> None:
    header = content_disposition("cv.pdf")

    assert header.startswith("attachment;")
    assert 'filename="cv.pdf"' in header
    assert "filename*=UTF-8''cv.pdf" in header


def test_non_ascii_names_are_encoded_and_have_a_plain_fallback() -> None:
    header = content_disposition("résumé.pdf")

    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in header
    assert 'filename="r_sum_.pdf"' in header


@pytest.mark.parametrize("nasty", ['a"b.pdf', "a\\b.pdf", "a;b.pdf", "a\r\nSet-Cookie: x=1.pdf"])
def test_a_name_cannot_break_out_of_the_header(nasty: str) -> None:
    header = content_disposition(clean_filename(nasty, PDF_TYPE))

    assert "\r" not in header and "\n" not in header
    ascii_part = header.split("filename*=")[0]
    # The quoted fallback is one plain token: no quote or backslash inside it.
    quoted = ascii_part.split('filename="', 1)[1].rsplit('"', 1)[0]
    assert '"' not in quoted and "\\" not in quoted
