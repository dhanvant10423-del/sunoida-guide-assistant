"""Look up missing product information on Sunoida's public website."""

from functools import lru_cache
from html.parser import HTMLParser
import logging
import re
from time import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from conversation import is_follow_up
from relevance_guard import terms
from source_pages import catalog


ORIGIN = "https://sunoida.com"


def website_url(value):
    url = urlsplit(urljoin(ORIGIN, value))
    if url.scheme != "https" or url.hostname not in {"sunoida.com", "www.sunoida.com"} or url.username or url.port not in (None, 443):
        return None
    return urlunsplit(("https", "sunoida.com", url.path or "/", url.query, ""))


class WebsitePage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.tag = None
        self.text = []
        self.paragraphs = []
        self.links = {}
        self.href = None
        self.link_text = []
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer", "header"}:
            self.skip += 1
        if self.skip:
            return
        if tag in {"p", "h1", "h2", "h3", "title"}:
            self.tag, self.text = tag, []
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.link_text = []

    def handle_data(self, data):
        if self.skip:
            return
        if self.tag:
            self.text.append(data)
        if self.href:
            self.link_text.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer", "header"}:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == self.tag:
            text = " ".join(" ".join(self.text).split())
            if tag == "title":
                self.title = text
            elif tag == "p" and len(text) >= 55 and text not in self.paragraphs:
                self.paragraphs.append(text)
            self.tag = None
        if tag == "a" and self.href:
            url = website_url(self.href)
            label = " ".join(" ".join(self.link_text).split())
            if url and label:
                self.links[url] = label
            self.href = None


@lru_cache(maxsize=40)
def fetch_page(url, cache_hour):
    del cache_hour
    with httpx.Client(timeout=12, follow_redirects=False, headers={"User-Agent": "SunoidaGuideAssistant/1.0"}) as client:
        for _ in range(4):
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = website_url(urljoin(url, response.headers.get("location", "")))
                    if not url:
                        raise ValueError("The website redirected outside sunoida.com.")
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise ValueError("The website page is too large.")
                parser = WebsitePage()
                parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
                return parser
    raise ValueError("The website redirected too many times.")


def lookup_terms(question):
    question = re.sub(r"\b(?:founded|established|started)\b", "incorporated", question, flags=re.IGNORECASE)
    return terms(question, question=True) - {
        "company", "sunoida", "website", "com", "sunuida", "app", "page", "screen", "button",
        "tell", "more", "solution", "solutions", "offer", "offering",
    }


def is_product_question(question, source, conversation):
    if re.search(r"\b(?:weather|recipe|cricket|football|bitcoin|cryptocurrency|horoscope|movie|joke|poem)\b", question, re.I):
        return False
    product = re.search(
        r"\b(?:sunoida|vision|etl|suptech|regtech|data quality|data governance|"
        r"revenue assurance|funds transfer pricing|banking bi)\b", question, re.I,
    )
    if product:
        return True
    return bool((source or (conversation and conversation.source)) and re.search(
        r"\b(?:it|this|that|app|application|connector|widget|dashboard|feed|monitor|rule|"
        r"export|import|user|profile|permission|report|pricing|license|licence|integration|deploy|"
        r"format|formats|support|supported|database|connection|workflow|authentication|login|"
        r"security|data|version|error|configuration|setting|settings)\b", question, re.I,
    ))


def website_fallback(question, source=None, conversation=None):
    if not is_product_question(question, source, conversation):
        return {
            "reply": "I can help with Sunoida products, their guides, and the screenshots or files you attach. Please ask a question about one of those.",
            "sources": [], "points": [], "status": "out_of_scope",
        }
    context_question = question
    if conversation and is_follow_up(question):
        context_question = f"{conversation.latest_query} {question}"
    topics = lookup_terms(context_question)
    cache_hour = int(time() // 3600)
    try:
        home = fetch_page(ORIGIN + "/", cache_hour)
        links = {
            **home.links,
            ORIGIN + "/our-profile/": "Sunoida company profile incorporated headquarters",
            ORIGIN + "/our-offices/": "Sunoida office contact address",
            ORIGIN + "/request-for-a-demo/": "Sunoida request demo",
        }
        ranked = sorted(links, key=lambda url: len(topics & terms(links[url] + " " + url)), reverse=True)
        pages = [(ORIGIN + "/", home)]
        for url in ranked[:3]:
            if url == ORIGIN + "/" or not (topics & terms(links[url] + " " + url)):
                continue
            try:
                pages.append((url, fetch_page(url, cache_hour)))
            except (httpx.HTTPError, ValueError):
                logging.debug("A Sunoida website page was unavailable", exc_info=True)
        matches = []
        for url, page in pages:
            for paragraph in page.paragraphs:
                if paragraph.startswith("*") or "License: CC" in paragraph:
                    continue
                overlap = topics & lookup_terms(paragraph)
                if overlap and len(overlap) >= min(2, len(topics)):
                    matches.append((len(overlap), url, page.title, paragraph))
        matches.sort(key=lambda item: item[0], reverse=True)
        if matches:
            best_url = matches[0][1]
            paragraphs = list(dict.fromkeys(item[3] for item in matches if item[1] == best_url))[:3]
            result = {
                "reply": "I couldn’t find this information in the user guides. Here’s what I found on Sunoida’s official website.\n\n"
                         + "\n\n".join(paragraphs),
                "sources": [], "points": [], "status": "answered", "answer_origin": "website",
                "web_sources": [{"title": matches[0][2] or "Sunoida official website", "url": best_url}],
            }
            if conversation:
                conversation.remember(question, result["reply"], question, source)
                conversation.latest_query = context_question
                conversation.latest_answer = result
                conversation.current_step = None
                conversation.pending_suggestion = None
            return result
        return {
            "reply": ("I couldn’t find this detail in the user guides or verify it on sunoida.com. "
                      "Could you name the screen, product version, or action you mean? You can also attach a screenshot so I can help narrow it down."),
            "sources": [], "points": [], "status": "clarification",
        }
    except (httpx.HTTPError, ValueError):
        return {
            "reply": ("I couldn’t find this detail in the user guides, and sunoida.com is currently unavailable. "
                      "Please try again later or share a screenshot of the feature you mean."),
            "sources": [], "points": [], "status": "clarification",
        }


def related_questions(question, result, source=None):
    questions = []
    suggestion = result.get("suggested_follow_up")
    if suggestion:
        questions.append(suggestion["question"])
    title = next((item["title"] for item in result.get("sources", [])), None)
    if not title and source:
        title = next((doc["title"] for doc in catalog().values() if doc["filename"] == source), None)
    if title:
        questions.append(f"What is {title}?")
        questions.append(f"What can {title} do?")
    for item in result.get("web_sources", []):
        label = item["title"].removeprefix("Sunoida: ").strip()
        if "profile" in label.casefold():
            questions.extend(["When was Sunoida founded?", "Where is Sunoida headquartered?",
                              "What banking analytics solutions does Sunoida provide?"])
        else:
            questions.append(f"What is {label}?")
            questions.append("When was Sunoida founded?")
    if not questions and re.search(r"\bsunoida\b", question, re.I):
        questions = ["What solutions does Sunoida offer?", "Tell me about Sunoida’s company profile."]
    return list(dict.fromkeys(q for q in questions if q.casefold() != question.casefold()))[:3]
