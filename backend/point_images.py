"""Resolve each answer point to real PDF page numbers and render them with Python."""

import logging
import re

from guide_figures import extract_figures


def page_label(pages):
    """Make a readable label using validated PDF metadata, not model guesses."""
    grouped = {}
    for page in pages:
        number, count = page.get("page"), page.get("page_count")
        if type(number) is not int or type(count) is not int or not 1 <= number <= count:
            continue
        title = page.get("title") or page.get("filename") or "Guide"
        grouped.setdefault(title, [])
        if number not in grouped[title]:
            grouped[title].append(number)
    labels = []
    for title, numbers in grouped.items():
        numbers.sort()
        noun = "page" if len(numbers) == 1 else "pages"
        labels.append(f"{title}, PDF {noun} " + ", ".join(str(number) for number in numbers))
    return "; ".join(labels)


def reply_with_page_labels(points):
    """Join answer points without adding repetitive page labels."""
    result = ""
    previous_kind = None
    for point in points:
        text = point["text"]
        kind = "ordered" if re.match(r"^\s*\d+[.)]\s+", text) else "bullet" if re.match(r"^\s*[-*]\s+", text) else None
        separator = "\n" if kind and kind == previous_kind else "\n\n"
        result += (separator if result else "") + text
        previous_kind = kind
    return result


def render_point_pages(blocks, references):
    """Keep answer text and attach extracted screenshots from validated sources.

    References come from retrieved guide metadata, not model-generated filenames
    or page guesses. The API serves the cached PNG using its existing page route.
    """
    sources = {source["index"]: source for source in references}
    rendered = {}
    points = []
    for block in blocks:
        indices = []
        pages = []
        seen = set()
        for index in block.get("source_indices", []):
            if type(index) is not int or index not in sources:
                continue
            source = sources[index]
            key = (source["document_id"], source["page"])
            if key in seen:
                continue
            seen.add(key)
            if key not in rendered:
                try:
                    rendered[key] = extract_figures(source["document_id"], source["page"])
                except Exception:
                    logging.exception("Could not extract embedded images for an answer point")
                    rendered[key] = []
            indices.append(index)
            pages.append({
                "index": index,
                "document_id": source["document_id"],
                "title": source["title"],
                "filename": source["filename"],
                "page": source["page"],
                "page_count": source["page_count"],
                "image_available": bool(rendered[key]),
                "image_url": None,
                "figures": rendered[key],
                "pdf_url": source["pdf_url"],
            })
        original = block.get("original_text", block["text"])
        label = page_label(pages)
        display = original
        points.append({
            "text": display, "original_text": original, "page_label": label,
            "source_indices": indices, "pages": pages,
        })
    # Image captions already identify their source page. For text-only sources,
    # keep the first explicit model citation and suppress later repetitions.
    cited = {page["index"] for point in points for page in point["pages"] if page["figures"]}
    valid = set(sources)
    def sparse_reference(match):
        if match[2] is None or int(match[2]) not in valid:
            return match[0]
        number = int(match[2])
        if number in cited:
            return ""
        cited.add(number)
        return match[0]
    for point in points:
        point["text"] = re.sub(r"(```[\s\S]*?```|`[^`\n]*`|\[(\d+)\])", sparse_reference, point["text"]).strip()
    return points


if __name__ == "__main__":
    import argparse
    from source_pages import catalog

    parser = argparse.ArgumentParser(description="Render one guide PDF page as a PNG.")
    parser.add_argument("--pdf", required=True, help="Exact filename from backend/docs")
    parser.add_argument("--page", required=True, type=int, help="Physical PDF page number, starting at 1")
    arguments = parser.parse_args()
    document = next((item for item in catalog().values() if item["filename"] == arguments.pdf), None)
    if document is None:
        parser.error("That filename does not match a PDF in backend/docs.")
    try:
        image_path = render_page(document["id"], arguments.page, size="full")
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    print(f"PDF page {arguments.page} rendered to: {image_path}")
