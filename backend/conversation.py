"""Bounded, process-local LangChain memory for independent browser conversations.

Only successfully grounded answers are remembered. Memory is context for resolving
follow-ups, never evidence for an answer. Restarting the server clears the store.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import re
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from config import settings

if TYPE_CHECKING:
    from attachments import Attachment


class ConversationBusyError(RuntimeError):
    pass


class ConversationScopeError(RuntimeError):
    pass


@dataclass
class MessageHistory:
    """Small bounded application buffer of LangChain message objects."""
    messages: list[BaseMessage] = field(default_factory=list)

    def add_messages(self, messages):
        self.messages.extend(messages)

    def clear(self):
        self.messages.clear()


@dataclass
class Conversation:
    history: MessageHistory = field(default_factory=MessageHistory)
    anchor: str = ""
    latest_query: str = ""
    latest_answer: dict | None = None
    current_step: int | None = None
    pending_suggestion: str | None = None
    source: str | None = None
    scope: str | None = None
    last_used: float = field(default_factory=monotonic)
    lock: Lock = field(default_factory=Lock)
    active: int = 0
    attachments: tuple[Attachment, ...] = ()

    def reset(self, scope=None):
        self.history.clear()
        self.anchor = ""
        self.latest_query = ""
        self.latest_answer = None
        self.current_step = None
        self.pending_suggestion = None
        self.source = None
        self.scope = scope
        self.attachments = ()

    def remember(self, question, reply, anchor, source):
        # Citation numbers refer to the CURRENT retrieval, not earlier turns.
        reply = re.sub(r"\[\d+\]", "", reply)
        question = question[:settings.history_max_chars // 2]
        self.history.add_messages([HumanMessage(content=question), AIMessage(content=reply)])
        self.anchor, self.source = anchor, source
        while len(self.history.messages) > settings.history_max_turns * 2 or (
            len(self.history.messages) > 2 and
            sum(len(item.content) for item in self.history.messages) > settings.history_max_chars
        ):
            del self.history.messages[:2]
        # An unusually long single answer is clipped in memory, not in the UI.
        budget = settings.history_max_chars - len(self.history.messages[-2].content)
        self.history.messages[-1].content = self.history.messages[-1].content[:max(0, budget)]


class ConversationStore:
    def __init__(self):
        self.sessions = {}
        self.lock = Lock()

    @contextmanager
    def use(self, session_id, scope=None):
        now = monotonic()
        with self.lock:
            expired = [key for key, item in self.sessions.items()
                       if not item.active and now - item.last_used >= settings.history_ttl_seconds]
            for key in expired:
                del self.sessions[key]
            if session_id not in self.sessions:
                if len(self.sessions) >= settings.history_max_sessions:
                    idle = [(item.last_used, key) for key, item in self.sessions.items() if not item.active]
                    if not idle:
                        raise ConversationBusyError("The assistant is busy. Please try again shortly.")
                    del self.sessions[min(idle)[1]]
                self.sessions[session_id] = Conversation(scope=scope)
            conversation = self.sessions[session_id]
            conversation.active += 1
        try:
            # Do not queue a second model call for a double-submitted conversation.
            if not conversation.lock.acquire(blocking=False):
                raise ConversationBusyError("This conversation already has an answer in progress.")
            try:
                if conversation.scope != scope:
                    raise ConversationScopeError("Start a new chat to choose another guide.")
                yield conversation
            finally:
                conversation.lock.release()
        finally:
            with self.lock:
                conversation.active -= 1
                conversation.last_used = monotonic()


store = ConversationStore()


STEP_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
STEP_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
STEP_REQUEST = re.compile(
    r"(?:what (?:is|was) |(?:can you )?(?:explain|show(?: me)?|expand on|repeat) )?"
    r"(?:the )?(?:(?:step|point)\s+(\d{1,3}|" + "|".join(STEP_NUMBERS) + r")|("
    + "|".join(STEP_ORDINALS) + r")\s+(?:step|point))",
    re.IGNORECASE,
)
NEXT_STEP = re.compile(
    r"(?:next|continue|what(?:'s| is) (?:the )?next(?: step)?|what happens (?:next|after that))",
    re.IGNORECASE,
)


def previous_step(message, conversation):
    """Resolve an exact step reference against the last displayed procedure."""
    if not conversation or not conversation.latest_answer:
        return None
    request = message.strip().rstrip("?.!")
    explicit = STEP_REQUEST.fullmatch(request)
    if explicit:
        if explicit[2]:
            number = STEP_ORDINALS[explicit[2].lower()]
        else:
            token = explicit[1].lower()
            number = int(token) if token.isdecimal() else STEP_NUMBERS[token]
    elif conversation.current_step is not None and NEXT_STEP.fullmatch(request):
        number = conversation.current_step + 1
    else:
        return None
    prior = conversation.latest_answer
    for point in prior["points"]:
        numbered = re.match(r"^\s*(\d+)[.)]\s+", point["text"])
        if numbered and int(numbered[1]) == number:
            indices = set(point.get("source_indices", []))
            sources = [source for source in prior["sources"] if source["index"] in indices] or prior["sources"]
            conversation.current_step = number
            return {
                "reply": point["text"], "points": [point], "sources": sources,
                "status": "answered", "used_history": True,
            }
    return {
        "reply": f"The previous answer has no step {number}. You can ask about a step it lists or name what you want to do next.",
        "points": [], "sources": [], "status": "clarification", "used_history": True,
    }


def is_follow_up(message):
    """Conservative English cues; a complete new question is searched on its own."""
    return bool(re.search(
        r"\b(?:it|its|that|this|these|those|them|they|their|above|previous|earlier)\b|"
        r"^\s*(?:and\b|also\b|what about\b|how about\b|continue\b|next\b|"
        r"explain (?:more|further|again|step)\b|(?:what(?:'s| is)?|which) (?:happens )?next\b)|"
        r"\b(?:explain|tell me|give me|describe)\s+(?:it\s+)?(?:more|further|again)\b|"
        r"\b(?:step|point)\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b|"
        r"\b(?:first|second|third|fourth|fifth|next|previous|last)\s+(?:step|point)\b|"
        r"\b(?:elaborate|summarize|summarise)\b|"
        r"\b(?:who|what) (?:approves|authorizes|authorises) (?:it|this|that|them)\b|"
        r"^\s*(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:give|show|provide)\s+"
        r"(?:me\s+)?(?:an?\s+)?(?:example|examples|details|summary)\b",
        message, re.IGNORECASE,
    ))


def resolve_follow_up(message, conversation):
    """Keep original topic plus new request, without asking a model to invent a query.

    In particular, never replace an unsupported new topic with an old supported
    topic. New content words remain in the relevance check. The answer chain also
    receives actual recent messages to understand step numbers and references.
    """
    if not conversation or not conversation.anchor or not is_follow_up(message):
        return message, False
    from search_guides import question_source
    # Naming a product explicitly starts a fresh topic, even if pronouns occur.
    if question_source(message):
        return message, False
    new_request = re.sub(
        r"\b(?:follow[- ]?up|continue|next|more|further|again|previous|earlier|above|"
        r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        r"one|two|three|four|five|six|seven|eight|nine|ten|"
        r"point|points|last|happens|happen|then|afterwards|them|they|their|"
        r"elaborate|summarize|summarise|summary|shorter|longer|simpler|simplify)\b",
        " ", message, flags=re.IGNORECASE,
    )
    from relevance_guard import terms
    if not terms(new_request, question=True):
        return conversation.latest_query or conversation.anchor, True
    return f"{conversation.anchor} {new_request}".strip(), True
