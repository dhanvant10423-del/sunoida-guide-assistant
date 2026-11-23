"""Answer common questions about screens and controls using guide evidence."""

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
ADD_CONTROL = r"""(?:(?:clicking|pressing) )?(?:the )?["'“”]?add["'“”]?(?: (?:button|icon))?"""
CONNECTOR_LOCATION = re.compile(
    r"\s+(?:in|within|on|from)\s+(?:the\s+)?(?:vision\s+)?etl"
    r"(?P<screen>\s+connector\s+config(?:uration)?(?:\s+(?:screen|page|module))?)?"
    r"(?:\s+app(?:lication)?)?$",
    re.IGNORECASE,
)


def connector_add_action(question):
    """Recognize questions about Add when a connector or its screen is named."""
    normal = " ".join(question.strip().rstrip(" ?!.").split())
    location = CONNECTOR_LOCATION.search(normal)
    request = normal[:location.start()] if location else normal
    match = re.fullmatch(
        rf"(?:(?:does|will|can) {ADD_CONTROL}|can i use {ADD_CONTROL} to) (create|add|start creating|save) "
        r"(?:an? |the )?(?:new )?(?:(?:data source|source|target|destination) )?connector",
        request, re.IGNORECASE,
    )
    if match:
        return match[1].casefold()
    if location and location["screen"] and re.fullmatch(rf"what does {ADD_CONTROL} do", request, re.IGNORECASE):
        return "describe"
    return None


def connector_add_answer(action, document):
    if document["short"] != "ETL":
        return None
    page = 12
    setup = " ".join(read_page_text(document, page).split())
    starts_setup = re.search(r"\bClick Add to create a new connector\.", setup, re.IGNORECASE)
    if not starts_setup:
        return None
    save_page = 17
    completion = " ".join(read_page_text(document, save_page).split())
    saves_connector = re.search(r"\bClick on Save button to save the connector\.", completion, re.IGNORECASE)
    if action == "save" and not saves_connector:
        return None
    references = [reference_for(document, page, 1, starts_setup[0])]
    lead = "**Add** starts a new connector in **ETL Connector Configuration**."
    if action in {"create", "add", "start creating"}:
        lead = f"Yes, {lead}"
    if action == "save":
        lead = "**Add** opens the setup form in **ETL Connector Configuration**."
    paragraphs = [lead]
    if re.search(
        r"\bMandatory Fields\b.*\bCountry\b.*\bLE Book\b.*\bConnector ID\b.*"
        r"\bConnection Name\b.*\bEndpoint Type\b.*\bConnector Type\b",
        setup,
    ):
        paragraphs.append(
            "Fill in the **General** section with the country, LE Book, a unique Connector ID, "
            "and a connection name. Then choose the endpoint and connector types and complete the configuration. [1]"
        )
    else:
        paragraphs[-1] += " [1]"
    if saves_connector:
        references.append(reference_for(document, save_page, 2, saves_connector[0]))
        finish = "When you finish the configuration, click **Save** to store the connector."
        if re.search(r"Approved connectors become available for:.*Feed configuration.*ETL execution", completion):
            finish += " After approval, you can use it in feed configuration and ETL execution."
        paragraphs.append(f"{finish} [2]")
    return {
        "reply": "\n\n".join(paragraphs), "sources": references, "points": [], "status": "answered",
        "chat_title": "Add a connector in Vision ETL",
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
