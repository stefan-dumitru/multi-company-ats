"""What counts as a resume file, and how its name is shown (security.md > File Upload Handling).

Pure rules, no storage and no database. The type is decided from the bytes, never from the
filename or from the type the browser claims.
"""

import io
import re
import unicodedata
import zipfile
from urllib.parse import quote

MAX_RESUME_BYTES = 5 * 1024 * 1024
PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_EXTENSIONS = {PDF_TYPE: ".pdf", DOCX_TYPE: ".docx"}

# A real Word file has a handful of parts. Only the list of names is read, never the content, so a
# zip bomb does nothing, but an absurd list is not a resume.
MAX_ZIP_ENTRIES = 1000
_DOCX_PARTS = {"[Content_Types].xml", "word/document.xml"}
_PDF_HEADER = re.compile(rb"%PDF-[12]\.\d")
_ZIP_HEADER = b"PK\x03\x04"

MAX_FILENAME_LENGTH = 255
_FALLBACK_NAME = "resume"
# Characters that reorder text on screen: "cv‮fdp.exe" would show as "cvexe.pdf".
_BIDI_CONTROLS = set("‎‏‪‫‬‭‮⁦⁧⁨⁩")


def detect_resume_type(data: bytes) -> str | None:
    """PDF or Word, as far as the bytes say; None for anything else."""
    if _PDF_HEADER.match(data):
        return PDF_TYPE
    if data.startswith(_ZIP_HEADER) and _looks_like_docx(data):
        return DOCX_TYPE
    return None


def _looks_like_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()  # reads the file list only
    except zipfile.BadZipFile, ValueError, OSError, NotImplementedError, RuntimeError:
        return False
    return len(names) <= MAX_ZIP_ENTRIES and _DOCX_PARTS <= set(names)


def clean_filename(raw: str, content_type: str) -> str:
    """The name to keep and show: a plain file name whose extension matches the real type.

    The name is display metadata only (the stored key is generated), so this is about not showing
    something misleading: no folders, no control or direction-changing characters, and an
    extension that says what the file really is.
    """
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        char
        for char in name
        if char not in _BIDI_CONTROLS and unicodedata.category(char) not in ("Cc", "Zl", "Zp")
    ).strip()
    if name in ("", ".", ".."):
        name = _FALLBACK_NAME
    extension = _EXTENSIONS[content_type]
    if not name.lower().endswith(extension):
        name += extension
    if len(name) > MAX_FILENAME_LENGTH:
        name = name[: -len(extension)][: MAX_FILENAME_LENGTH - len(extension)] + extension
    return name


def content_disposition(filename: str) -> str:
    """The download header: a plain-ASCII fallback name, and the real name encoded (RFC 5987)."""
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
