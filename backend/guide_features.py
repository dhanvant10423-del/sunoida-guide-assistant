"""Resolve feature-availability questions to documented screens."""

import re

from guide_overview import APPLICATION
from search_guides import question_source
from source_pages import read_page_text, reference_for


FEATURE_CHECK = re.compile(
    r"^(?:does (?P<product>.+?) have(?: have)*|is there) (?:an? |the )?(?P<feature>.+)$",
    re.IGNORECASE,
)
MONITOR_NAMES = {"monitor", "monitoring", "data monitor", "monitor dashboard", "monitoring dashboard"}
MONITOR_SECTIONS = {
    "ETL": (6, "Monitor Dashboard", r"\bMonitor Dashboard (The Dashboard (provides [^.]+\.))"),
    "DQ": (92, "Data Monitor", r"\b(The Data Monitor (shows [^.]+\.))"),
}


def feature_check(question):
    """Return the feature and any explicitly named product in a yes/no question."""
    normal = " ".join(question.strip().rstrip(" ?!.").split())
    match = FEATURE_CHECK.fullmatch(normal)
    if not match:
        return None
    subject = match["product"]
    source = None
    if subject and not re.fullmatch(APPLICATION, subject, re.IGNORECASE):
        source = question_source(subject)
        if not source:
            return None
    feature = match["feature"]
    trailing = re.fullmatch(r"(.+) in (.+)", feature, re.IGNORECASE)
    if trailing:
        location_source = question_source(trailing[2])
        if location_source or re.fullmatch(APPLICATION, trailing[2], re.IGNORECASE):
            if source and location_source and source != location_source:
                return None
            source = source or location_source
            feature = trailing[1]
    feature = re.sub(r"\s+(?:page|screen|tab|module|section)s?$", "", feature, flags=re.IGNORECASE)
    return feature, source


def documented_feature(feature, document):
    """Answer from verified descriptions of the guide's monitor screen."""
    section = MONITOR_SECTIONS.get(document["short"])
    if feature.casefold() not in MONITOR_NAMES or section is None:
        return None
    page, name, description = section
    raw = read_page_text(document, page)
    evidence = re.search(description, " ".join(raw.split()))
    if not evidence:
        return None
    references = [reference_for(document, page, 1, evidence[1])]
    reply = f"Yes, **{document['title']}** has a monitoring page called **{name}**. It {evidence[2]} [1]"
    if document["short"] == "DQ" and re.search(r"^SIDEBAR Monitor\s*$", raw, re.MULTILINE):
        reply += "\n\nOpen **Monitor** in the sidebar."
    if document["short"] == "ETL":
        console_page = 4
        console = " ".join(read_page_text(document, console_page).split())
        if re.search(r"\bETL Console\b.*\bprimary sections\b.{0,55}\bDashboard\b", console):
            references.append(reference_for(document, console_page, 2))
            reply += "\n\nOpen **ETL Console → Dashboard**. [2]"
    return {
        "reply": reply, "sources": references, "points": [], "status": "answered",
        "chat_title": f"{name} in {document['title']}",
    }


def unconfirmed_feature(feature, document, reason):
    return {
        "reply": f"I couldn’t verify **{feature}** in the **{document['title']}** guide.",
        "sources": [], "points": [], "status": "not_found", "reason": reason,
    }
