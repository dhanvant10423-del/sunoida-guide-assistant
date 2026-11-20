"""Suggest one related question that can be answered from the same guide."""

import logging
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from config import settings
from relevance_guard import supported_sources, terms
from search_guides import MIN_SIMILARITY, search_guides

ETL_SETUP_REQUEST = re.compile(
    r"(?:how (?:do|can|should) (?:i|we|you) |how to |steps to )"
    r"(?:configure|set up|create) (?:an? |the |a new )?etl feed"
    r"(?: in vision etl)?[?.!]*",
    re.IGNORECASE,
)

# These workflow links take precedence when the question is about the
# corresponding starting point. Every suggested question is checked below.
WORKFLOW_LINKS = {
    "ETL": (
        ETL_SETUP_REQUEST,
        "Do you want to know how to publish it?",
        "How do I publish an ETL feed in Vision ETL?",
    ),
    "API": (
        re.compile(r"\b(?:create|configure|set up|add)\b.*\bpush api\b", re.IGNORECASE),
        "Do you want to know how to add the API version to a group?",
        "How do I configure an API group in Vision API Manager?",
    ),
    "DQ": (
        re.compile(r"\b(?:data quality|dq|quality) scores?\b", re.IGNORECASE),
        "Do you want to know where to see the Data Trust Score?",
        "How do I see the Data Trust Score in Vision AI Data Quality?",
    ),
    "ST": (
        re.compile(r"\b(?:what can|overview|what (?:is|are))\b.*\bdashboards?\b", re.IGNORECASE),
        "Do you want to know how to use dashboard filters?",
        "How do I use dashboard filters in Vision Studio?",
    ),
}

proposal_chain = ChatPromptTemplate.from_messages([
    ("system", "Write one brief, useful next question in the user's voice. It must address a different "
     "aspect of the same task or feature, and the guide excerpts must contain its answer. "
     "Use the guide's exact feature names. Return only a standalone question, or NONE."),
    ("human", "Guide: {title}\nExcerpts:\n{evidence}\nUser asked: {question}\n"
     "Answer already given: {answer}\nWhat different question could the user ask next?"),
]) | ChatOllama(
    model=settings.chat_model, base_url=settings.ollama_url,
    temperature=0, num_ctx=settings.context_window, num_predict=48,
    client_kwargs={"timeout": min(settings.ollama_timeout, 12)},
) | StrOutputParser()

CONTENTS_MARKERS = re.compile(r"\.{8,}")
GUIDE_ACTION = re.compile(
    r"•\s*(Open|Define|Select|Assign|Create|Compare|Manage|Set|Configure|Add|Calculate|"
    r"Publish|View|Review|Run|Apply|Filter|Deploy|Import|Export|Check|Monitor)\s+"
    r"([A-Za-z][\w -]{4,60}?)(?=\s+(?:for|from|with|using|on|to|by|and)\b|[.;,:•]|\s*$)",
    re.IGNORECASE,
)


def can_answer(question, filename):
    matches = search_guides(question, limit=settings.retrieval_top_k, source=filename)
    passages = [{"index": index, "text": match["text"]} for index, match in enumerate(matches)
                if match["similarity"] >= MIN_SIMILARITY and not CONTENTS_MARKERS.search(match["text"])]
    return bool(supported_sources(question, passages))


def extract_questions(excerpts):
    """Try a few actions written explicitly in guide lists."""
    for excerpt in excerpts:
        for action in GUIDE_ACTION.finditer(excerpt):
            yield f"How do I {action[1].lower()} {action[2].strip()}?"


def check_proposal(proposal, document, topics_in_evidence, earlier_topics):
    match = re.fullmatch(r"((?:how|what|where|when|which|who|why|can|does|do)\b[^?\r\n]{7,155})\?",
                         proposal, re.IGNORECASE)
    if not match:
        return None
    topics = terms(proposal, question=True)
    if not topics or any(topics <= previous for previous in earlier_topics):
        return None
    if len(topics & topics_in_evidence) < min(len(topics), 2):
        return None
    from search_guides import question_source
    filename = document["filename"]
    proposed_source = question_source(proposal)
    if proposed_source and proposed_source != filename:
        return None
    standalone = proposal if proposed_source else f"{match[1]} in {document['title']}?"
    if not can_answer(standalone, filename):
        return None
    action = re.fullmatch(r"how (?:do|can) i (.+)\?", proposal, re.IGNORECASE)
    prompt = f"Do you want to know how to {action[1]}?" if action else proposal
    return {"prompt": prompt, "question": standalone}


def offer_for(question, answer, candidates, earlier_questions=()):
    filenames = {candidate["document"]["filename"] for candidate in candidates}
    if len(filenames) != 1:
        return None
    document = candidates[0]["document"]
    filename, short = document["filename"], document.get("short")
    known = WORKFLOW_LINKS.get(short)
    earlier_topics = [terms(previous, question=True) for previous in (*earlier_questions, question)]
    try:
        if known and known[0].search(question):
            _, prompt, next_question = known
            if terms(next_question, question=True) not in earlier_topics and can_answer(next_question, filename):
                return {"prompt": prompt, "question": next_question}
        # Exclude index pages, whose headings alone cannot answer a question.
        excerpts = [item["text"] for item in candidates if not CONTENTS_MARKERS.search(item["text"])]
        if not excerpts:
            return None
        topics_in_evidence = terms(" ".join(excerpts))
        # Explicit guide actions are quick to check and survive a model timeout.
        options = list(dict.fromkeys(extract_questions(excerpts)))[:3]
        for proposal in options:
            suggestion = check_proposal(proposal, document, topics_in_evidence, earlier_topics)
            if suggestion:
                return suggestion
        proposal = proposal_chain.invoke({
            "title": document["title"], "evidence": "\n\n".join(excerpts)[:3600],
            "question": question, "answer": answer[:750],
        }).strip().strip('"')
        return check_proposal(proposal, document, topics_in_evidence, earlier_topics)
    except Exception:
        # A failed optional suggestion must not discard the guide answer.
        logging.debug("Could not suggest a follow-up", exc_info=True)
        return None
