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
    text = " ".join(raw.split())
    evidence = re.search(description, text)
    if not evidence:
        return None
    references = [reference_for(document, page, 1, evidence[1])]
    paragraphs = [f"Yes, **{document['title']}** has a monitoring page called **{name}**. It {evidence[2]}"]
    if document["short"] == "DQ":
        if re.search(
            r"results of your approved rules \(by table, by column and by version\).*?"
            r"data timeliness, volume, schema changes and data pattern shift",
            text, re.IGNORECASE,
        ):
            paragraphs.append(
                "You can review **approved-rule results** by table, column, or version. "
                "The page also tracks whether data arrives on time and whether its volume, "
                "schema, or patterns have changed."
            )
        if "rule pass rate" in text and re.search(
            r"which column or rule is responsible, and see exactly what changed since the previous run",
            text, re.IGNORECASE,
        ):
            paragraphs.append(
                "For example, if a table’s rule pass rate drops, you can check which column "
                "or rule needs attention and see what changed since the previous run."
            )
    if document["short"] == "ETL" and re.search(
        r"Widget Menu.*selected widgets are saved as the default view", text, re.IGNORECASE,
    ):
        paragraphs.append(
            "If you regularly check the same metrics, choose the widgets you need and save them "
            "as your default view. The ETL Console will display those widgets when it opens."
        )
    paragraphs[-1] += " [1]"
    if document["short"] == "DQ" and re.search(r"^SIDEBAR Monitor\s*$", raw, re.MULTILINE):
        paragraphs.append("Open **Monitor** in the sidebar.")
    if document["short"] == "ETL":
        console_page = 4
        console = " ".join(read_page_text(document, console_page).split())
        if re.search(r"\bETL Console\b.*\bprimary sections\b.{0,55}\bDashboard\b", console):
            references.append(reference_for(document, console_page, 2))
            paragraphs.append("Open **ETL Console → Dashboard**. [2]")
    return {
        "reply": "\n\n".join(paragraphs), "sources": references, "points": [], "status": "answered",
        "chat_title": f"{name} in {document['title']}",
    }


def unconfirmed_feature(feature, document, reason):
    return {
        "reply": f"I couldn’t verify **{feature}** in the **{document['title']}** guide.",
        "sources": [], "points": [], "status": "not_found", "reason": reason,
    }
