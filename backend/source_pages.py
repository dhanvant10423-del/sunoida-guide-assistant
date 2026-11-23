"""Serve real guide pages, with local caching and an allow-listed PDF catalog."""

import hashlib
import os
import threading
from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pypdfium2 as pdfium
from config import settings

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = settings.docs_dir
CACHE_DIR = settings.cache_dir
PDF_LOCK = threading.RLock()  # PDFium calls must not run concurrently in threads.


def guide_title(filename):
    name = filename.lower()
    for text, title, short in [
        ("api_manager", "Vision API Manager", "API"),
        ("visionetl", "Vision ETL", "ETL"),
        ("visionstudio", "Vision Studio", "ST"),
        ("data quality", "Vision AI Data Quality", "DQ"),
        ("vision_bi", "Vision BI", "BI"),
        ("tax_assurance", "Vision Tax Assurance", "TAX"),
    ]:
        if text in name:
            return title, short
    return Path(filename).stem.replace("_", " "), "PDF"


def catalog():
    documents = {}
    for candidate in sorted(DOCS_DIR.glob("*.pdf")):
        path = candidate.resolve()
        if path.parent != DOCS_DIR:
            continue
        document_id = hashlib.sha256(candidate.name.encode("utf-8")).hexdigest()[:20]
        title, short = guide_title(candidate.name)
        documents[document_id] = {
            "id": document_id, "filename": candidate.name,
            "title": title, "short": short, "path": path,
        }
    return documents


def get_document(document_id):
    document = catalog().get(document_id)
    if document is None:
        raise FileNotFoundError("This guide is not available in backend/docs.")
    return document


@lru_cache(maxsize=64)
def _page_count(path, modified_ns, size):
    with PDF_LOCK:
        with pdfium.PdfDocument(path) as pdf:
            return len(pdf)


def page_count(document):
    stat = document["path"].stat()
    return _page_count(str(document["path"]), stat.st_mtime_ns, stat.st_size)


def public_guides():
    result = []
    for document in catalog().values():
        item = {key: document[key] for key in ["id", "filename", "title", "short"]}
        try:
            item["pages"] = page_count(document)
            item["available"] = item["pages"] > 0
        except Exception:
            item.update(pages=0, available=False)
        item["pdf_url"] = f"/api/guides/{document['id']}/pdf"
        result.append(item)
    return sorted(result, key=lambda item: item["title"])


def reference_for(document, page, index, excerpt=""):
    count = page_count(document)
    if not 1 <= page <= count:
        raise ValueError("That PDF page does not exist.")
    base = f"/api/guides/{document['id']}"
    return {
        "index": index, "document_id": document["id"],
        "title": document["title"], "filename": document["filename"],
        "page": page, "page_count": count, "excerpt": excerpt[:260],
        "image_url": f"{base}/pages/{page}/preview?size=thumb",
        "preview_url": f"{base}/pages/{page}/preview?size=full",
        "pdf_url": f"{base}/pdf#page={page}",
    }


def read_page_text(document, page):
    if not 1 <= page <= page_count(document):
        return ""
    with PDF_LOCK, pdfium.PdfDocument(document["path"]) as pdf:
        with closing(pdf[page - 1]) as sheet, closing(sheet.get_textpage()) as text:
            return text.get_text_bounded()


def render_page(document_id, page_number, size="thumb"):
    document = get_document(document_id)
    if not 1 <= page_number <= page_count(document):
        raise ValueError("That PDF page does not exist.")
    target_width = 560 if size == "thumb" else 1400
    stat = document["path"].stat()
    signature = f"{document_id}:{stat.st_mtime_ns}:{stat.st_size}:{page_number}:{target_width}"
    key = hashlib.sha256(signature.encode()).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    image_path = CACHE_DIR / f"{key}.png"
    with PDF_LOCK:
        if not image_path.exists():
            with pdfium.PdfDocument(str(document["path"])) as pdf:
                page = pdf[page_number - 1]
                width, height = page.get_size()
                # Bound both dimensions even for unusual page aspect ratios.
                scale = min(target_width / width, 2200 / height, 2.5)
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    try:
                        temporary = image_path.with_suffix(".tmp")
                        image.save(temporary, format="PNG")
                        os.replace(temporary, image_path)
                    finally:
                        image.close()
                finally:
                    bitmap.close()
                    page.close()
    return image_path
