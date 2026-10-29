"""PDF bytes -> text with page markers. The page markers let claims cite a page."""

import io

import pypdf


def pdf_to_text(data):
    reader = pypdf.PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        pages.append(f"=== page {i} ===\n{(page.extract_text() or '').strip()}")
    text = "\n\n".join(pages)
    if len(text) < 200 * max(1, len(reader.pages)) // 4:
        # Scanned PDFs (e.g. St. Charles County minutes) have no text layer. Fail loudly
        # instead of handing the agents an empty document. OCR is ticket T-6.
        raise ValueError(f"PDF has almost no extractable text ({len(text)} chars, {len(reader.pages)} pages); likely scanned")
    return text
