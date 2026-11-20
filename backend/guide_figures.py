"""Extract substantial embedded guide images without rendering page prose."""

import hashlib
import json
import math
import os
import re

import pypdfium2 as pdfium
from source_pages import CACHE_DIR, PDF_LOCK, get_document, page_count

EXTRACTION_VERSION = "embedded-figures-v1"
FIGURE_DIR = CACHE_DIR / "figures"


def extract_figures(document_id, page_number):
    document = get_document(document_id)
    if type(page_number) is not int or not 1 <= page_number <= page_count(document):
        raise ValueError("That PDF page does not exist.")
    stat = document["path"].stat()
    signature = f"{EXTRACTION_VERSION}:{document_id}:{page_number}:{stat.st_mtime_ns}:{stat.st_size}"
    cache_key = hashlib.sha256(signature.encode()).hexdigest()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = FIGURE_DIR / f"{cache_key}.json"
    with PDF_LOCK:
        if manifest.is_file():
            try:
                figures = json.loads(manifest.read_text(encoding="utf-8"))
                if all(re.fullmatch(r"[a-f0-9]{32}", item["figure_id"]) and
                       (FIGURE_DIR / f"{item['figure_id']}.png").is_file() for item in figures):
                    return figures
            except (ValueError, KeyError, TypeError):
                pass
        figures, seen = [], set()
        with pdfium.PdfDocument(str(document["path"])) as pdf:
            page = pdf[page_number - 1]
            try:
                page_width, page_height = page.get_size()
                candidates = []
                for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]):
                    left, bottom, right, top = obj.get_bounds()
                    width, height = right - left, top - bottom
                    pixel_width, pixel_height = obj.get_px_size()
                    if not all(math.isfinite(n) for n in (left, bottom, right, top)):
                        continue
                    # Exclude small icons, header logos, footer artwork and
                    # whole-page scans, which could reintroduce page prose.
                    centre = (bottom + top) / 2
                    coverage = width * height / (page_width * page_height)
                    if (pixel_width < 240 or pixel_height < 120 or width < 130 or height < 60
                            or pixel_width * pixel_height > 40_000_000
                            or not 0.17 * page_height < centre < 0.91 * page_height
                            or not 0.02 <= coverage <= 0.85):
                        continue
                    candidates.append((top, left, obj))
                for _, _, obj in sorted(candidates, key=lambda item: (-item[0], item[1])):
                    bitmap = obj.get_bitmap(render=True)
                    try:
                        image = bitmap.to_pil().convert("RGB")
                        try:
                            digest = hashlib.sha256(
                                f"{image.width}:{image.height}:RGB".encode() + image.tobytes()
                            ).hexdigest()[:32]
                            if digest in seen:
                                continue
                            seen.add(digest)
                            target = FIGURE_DIR / f"{digest}.png"
                            if not target.exists():
                                temporary = target.with_suffix(".tmp")
                                image.save(temporary, format="PNG")
                                os.replace(temporary, target)
                            figures.append({
                                "figure_id": digest,
                                "width": image.width, "height": image.height,
                                "image_url": f"/api/guides/{document_id}/pages/{page_number}/figures/{digest}",
                            })
                        finally:
                            image.close()
                    finally:
                        # PDFium owns this buffer; its finalizer frees it after
                        # all borrowed views are gone. The saved PIL image is a copy.
                        bitmap = None
                    if len(figures) >= 3:
                        break
            finally:
                page.close()
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(figures), encoding="utf-8")
        os.replace(temporary, manifest)
        return figures


def figure_path(document_id, page_number, figure_id):
    if not re.fullmatch(r"[a-f0-9]{32}", figure_id):
        raise FileNotFoundError("That guide image is not available.")
    if not any(item["figure_id"] == figure_id for item in extract_figures(document_id, page_number)):
        raise FileNotFoundError("That image does not belong to this guide page.")
    return FIGURE_DIR / f"{figure_id}.png"
