"""Answer product-level questions from the guide's introduction."""

import re

from source_pages import read_page_text, reference_for


INTRO_PAGES = {"API": 5, "BI": 8, "DQ": 3, "ETL": 4, "ST": 3, "TAX": 3}
APPLICATION = r"(?:(?:this|the|the selected|that) (?:app|application|product|software|system)|it)"
OVERVIEW_REQUEST = (
    r"(?:(?:tell me about|explain(?: about)?|describe|summari[sz]e|what is|"
    r"what's|give me (?:an? )?(?:overview|introduction) (?:of|to)) {subject}|"
    r"(?:an? )?(?:overview|introduction)(?: (?:of|to)| for)? {subject}|"
    r"what (?:can|does) {subject} do|what is {subject} used for|"
    r"what (?:are|is) (?:the )?(?:main |key )?(?:features|purpose) of {subject})"
)


def is_overview(question, document=None):
    normal = " ".join(question.casefold().strip().rstrip("?.!").split())
    subjects = [APPLICATION]
    if document:
        title = document["title"].casefold()
        subjects.append(r"(?:vision )?" + re.escape(title.removeprefix("vision ")))
        if document.get("short") == "BI":
            subjects.append(r"(?:vision )?business intelligence")
        elif document.get("short") == "DQ":
            subjects.append(r"(?:vision )?data quality")
    return normal in {"overview", "introduction"} or re.fullmatch(
        OVERVIEW_REQUEST.format(subject="(?:" + "|".join(subjects) + ")"), normal,
    ) is not None


def product_overview(document):
    page = INTRO_PAGES.get(document.get("short"))
    if page is None:
        return None
    title = "Vision Business Intelligence (BI)" if document["short"] == "BI" else document["title"]
    text = re.sub(r"\s+", " ", read_page_text(document, page)).replace("\ufffd", "’")
    opening = re.search(
        rf"\b{re.escape(title)} (?:is|measures)\b.*?[.!?](?=\s|$)(?:\s+[^.!?]+[.!?](?=\s|$))?",
        text, re.IGNORECASE,
    )
    if not opening:
        return None
    summary = opening[0]
    references = [reference_for(document, page, 1, summary)]
    result = {
        "reply": f"{summary} [1]", "sources": references,
        "points": [], "status": "answered", "used_history": False,
        "chat_title": f"{document['title']} overview",
    }
    if document["short"] == "DQ":
        workflow_page = 4
        workflow = read_page_text(document, workflow_page)
        section = re.search(r"How it works: from source to decision(.*?)The two headline scores", workflow, re.DOTALL)
        if section:
            actions = re.findall(
                r"(?m)^(?:\d+ )?(Connect a source|Choose tables|Choose rules|Run|Explore the result|Decide)\.",
                section[1],
            )
            if len(actions) == 6:
                references.append(reference_for(document, workflow_page, 2))
                result["workflow"] = {"steps": actions, "source_index": 2}
    return result
