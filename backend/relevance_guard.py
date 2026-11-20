"""Conservative topic and evidence checks before generating a guide answer."""

from collections import Counter
from functools import lru_cache
import re

NO_GUIDE_ANSWER = (
    "I couldn't find enough information in the Sunoida guides to answer that question. "
    "I can help with Vision ETL, Studio, BI, API Manager, AI Data Quality and Tax Assurance. "
    "Please name the product and the feature or screen you need help with."
)

# Request words and product names provide context, but do not by themselves
# demonstrate that a requested feature or fact is documented.
REQUEST_WORDS = set("""
a an the and or of in on at by to for from with without into about between
is are was were be been being do does did have has had can could would should
will shall may might must i me my we our you your it its this that these those
what which who whom whose why how when where there any some all only also as
please kindly help assist assistance tell explain describe define give provide
show find view read list know understand learn want need get let step steps procedure process
way ways use using used work works working perform set up setup configure
configuration create creating created add adding new make making run running
required require requirement requirements write written generate example code
feature features purpose benefit benefits advantage advantages overview detail
details information guide guides manual manuals document documentation product
application system vision sunoida etl studio bi api manager ai data quality tax
assurance then now today really exactly properly correctly simple simply
after before
""".split())

ALIASES = {
    "administrator": "admin", "administrators": "admin", "superadmin": "admin",
    "permission": "access", "permissions": "access",
    "logs": "audit", "log": "audit", "logging": "audit",
    "notifications": "alert", "notification": "alert", "notify": "alert", "alerts": "alert",
    "queries": "query", "countries": "country", "categories": "category",
    "scores": "score", "scored": "score", "scoring": "score",
    "approval": "authorize", "approvals": "authorize", "approve": "authorize",
    "approves": "authorize", "approved": "authorize", "approving": "authorize",
    "authorization": "authorize", "authorisation": "authorize",
    "authorizes": "authorize", "authorises": "authorize", "authorized": "authorize",
    "authorised": "authorize", "authorizing": "authorize", "authorising": "authorize",
    "settings": "setting", "config": "configur", "configuration": "configur",
}

# In definition questions, "mean" describes what the user wants us to do.
# Keep it as a topic in phrases such as "mean absolute error".
DEFINITION_VERB = re.compile(
    r"(\bwhat\s+(?:do|does|did)\b[^?!.]*?)\bmean\b(?=\s*(?:[?!.]|$|\b(?:in|for|on|by)\b))"
)


def refusal(reason="no_support"):
    return {"reply": NO_GUIDE_ANSWER, "sources": [], "points": [], "status": "not_found", "reason": reason}


def greeting_reply(message):
    normal = re.sub(r"[^a-z\s]", "", message.casefold()).strip()
    if normal in {"hi", "hello", "hey", "good morning", "good evening", "help", "what can you do", "who are you"}:
        return {"reply": "Hello! I can answer questions about your Sunoida product guides. Which product or feature would you like help with?",
                "sources": [], "points": [], "status": "greeting"}
    return None


def _stem(word):
    word = ALIASES.get(word, word)
    if len(word) == 5 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    if len(word) > 5:
        for suffix in ("ations", "ation", "ing", "ied", "ed", "es", "s", "e"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                return word[:-len(suffix)]
    return word


def terms(text, question=False):
    text = text.casefold().replace("e-mail", "email")
    if question:
        text = DEFINITION_VERB.sub(r"\1", text)
    words = re.findall(r"[a-z][a-z0-9]*", text)
    return {_stem(word) for word in words if len(word) >= 3 and
            (not question or (word not in REQUEST_WORDS and not word.endswith("ly")))}


@lru_cache(maxsize=1)
def topic_frequencies():
    from search_guides import database, COLLECTION_NAME
    collection = database().get_collection(name=COLLECTION_NAME, embedding_function=None)
    documents = collection.get(include=["documents"])["documents"]
    frequency = Counter()
    for text in documents:
        frequency.update(terms(text or ""))
    return frequency


def supported_sources(message, passages, client=None):
    """Choose passages containing the question's two most distinctive topics.

    The semantic cutoff runs first. This deterministic check deliberately favours
    abstention over inferring undocumented facts. It is a heuristic and may
    decline valid paraphrases; it does not certify answer correctness.
    """
    if not passages:
        return []
    topics = terms(message, question=True)
    if not topics:
        return list(dict.fromkeys(passage["index"] for passage in passages))
    frequency = topic_frequencies()
    anchors = sorted(topics, key=lambda word: (frequency[word], word))[:2]
    approved = []
    for passage in passages:
        if set(anchors).issubset(terms(passage["text"])) and passage["index"] not in approved:
            approved.append(passage["index"])
    return approved
