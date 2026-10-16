from io import BytesIO

from pypdf import PdfReader

MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 40
MAX_RESUME_CHARS = 40_000


class ResumeImportError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def extract_resume_text(pdf_bytes: bytes) -> str:
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ResumeImportError("pdf_too_large")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ResumeImportError("invalid_pdf")
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=True)
        if reader.is_encrypted:
            raise ResumeImportError("encrypted_pdf")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ResumeImportError("too_many_pages")
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except ResumeImportError:
        raise
    except Exception as error:
        raise ResumeImportError("invalid_pdf") from error
    if not text:
        raise ResumeImportError("no_extractable_text")
    if len(text) > MAX_RESUME_CHARS:
        raise ResumeImportError("resume_text_too_long")
    return text
