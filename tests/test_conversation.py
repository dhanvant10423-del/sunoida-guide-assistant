"""Exercise conversation isolation and grounded follow-ups without model calls."""

from collections import Counter
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

import ai_client
import conversation
from conversation import Conversation, ConversationBusyError, ConversationScopeError, ConversationStore, resolve_follow_up
import main


class MemoryTests(unittest.TestCase):
    def test_expiry_capacity_and_busy_sessions(self):
        store = ConversationStore()
        limits = conversation.settings.model_copy(update={"history_max_sessions": 1, "history_ttl_seconds": 60})
        with patch.object(conversation, "settings", limits):
            with store.use("first") as first:
                with self.assertRaises(ConversationBusyError):
                    with store.use("second"):
                        pass
                with self.assertRaises(ConversationBusyError):
                    with store.use("first"):
                        pass
                first.anchor = "old topic"
            with store.use("second"):
                self.assertNotIn("first", store.sessions)
            store.sessions["second"].last_used -= 61
            with store.use("second") as expired:
                self.assertFalse(expired.anchor)

    def test_scope_change_and_trimming(self):
        store = ConversationStore()
        limits = conversation.settings.model_copy(update={"history_max_turns": 2, "history_max_chars": 1000})
        with patch.object(conversation, "settings", limits):
            with store.use("one", "ETL.pdf") as item:
                for i in range(4):
                    item.remember(f"question{i}", "answer [1] " * 60, "feed", "ETL.pdf")
                self.assertLessEqual(len(item.history.messages), 4)
                self.assertLessEqual(sum(len(m.content) for m in item.history.messages), 1000)
                self.assertNotIn("[1]", item.history.messages[-1].content)
            with self.assertRaises(ConversationScopeError):
                with store.use("one", "BI.pdf"):
                    pass
            with store.use("one", "ETL.pdf") as unchanged:
                self.assertEqual(unchanged.anchor, "feed")
                self.assertTrue(unchanged.history.messages)
                unchanged.remember("q" * 2000, "a" * 3000, "topic", "ETL.pdf")
                self.assertLessEqual(sum(len(m.content) for m in unchanged.history.messages), 1000)

    def test_follow_up_keeps_new_unsupported_topic(self):
        item = Conversation(anchor="How do I configure a feed in Vision ETL?")
        query, used = resolve_follow_up("Can it predict cryptocurrency prices?", item)
        self.assertTrue(used)
        self.assertIn("cryptocurrency prices", query)
        self.assertIn("Vision ETL", query)
        query, used = resolve_follow_up("How do I create a dashboard in Vision Studio?", item)
        self.assertFalse(used)
        self.assertNotIn("ETL", query)

    def test_common_follow_up_phrasings(self):
        item = Conversation(anchor="How do I configure a feed in Vision ETL?")
        for message in ["What's the next step?", "Explain the second point", "Can you explain more?",
                        "Give me an example", "Summarize it", "Can you elaborate?"]:
            with self.subTest(message=message):
                query, used = resolve_follow_up(message, item)
                self.assertTrue(used)
                self.assertIn("Vision ETL", query)

    def test_step_navigation_keeps_latest_procedure_and_source(self):
        from conversation import previous_step
        item = Conversation(
            anchor="How do I configure a feed in Vision ETL?",
            latest_query="How do I publish an ETL feed?",
            latest_answer={
                "points": [
                    {"text": "2. Click Publish.", "source_indices": [1]},
                    {"text": "3. The feed moves to Pending.", "source_indices": [1]},
                ],
                "sources": [{"index": 1, "page": 34}],
            },
        )
        self.assertEqual(previous_step("Explain the second point", item)["reply"], "2. Click Publish.")
        following = previous_step("What is the next step?", item)
        self.assertEqual(following["reply"], "3. The feed moves to Pending.")
        self.assertEqual(following["sources"][0]["page"], 34)
        self.assertEqual(previous_step("Next", item)["status"], "clarification")
        self.assertEqual(resolve_follow_up("Tell me more", item), (item.latest_query, True))


class ConversationApiTests(unittest.TestCase):
    def setUp(self):
        self.store = ConversationStore()
        self.prompts = []
        self.queries = []
        self.decline = False
        self.fail = False

        def model(prompt):
            self.prompts.append(prompt.to_messages())
            if self.fail:
                raise RuntimeError("test model failure")
            return AIMessage(content="NO_GUIDE_ANSWER" if self.decline else "1. Configure the feed. [1]\n2. Publish the feed. [1]")

        def search(question, limit, source):
            self.queries.append((question, source))
            return [{"text": "In Vision ETL, configure the feed. Publish the feed for approval by the Checker. "
                             "User Access Management \u2013 UAM Profile Setup uses the System Admin menu.",
                     "source": "ETL.pdf", "page": 34, "similarity": .99}]

        fake_chain = ai_client.answer_chain.steps[0] | RunnableLambda(model) | StrOutputParser()
        patches = [
            patch.object(main, "store", self.store),
            patch.object(ai_client, "answer_chain", fake_chain),
            patch.object(ai_client, "search_guides", side_effect=search),
            patch.object(ai_client, "catalog", return_value={"etl": {"filename": "ETL.pdf", "id": "etl", "short": "ETL"}}),
            patch.object(ai_client, "reference_for", side_effect=lambda doc, page, index, text:
                         {"index": index, "filename": doc["filename"], "title": "Vision ETL", "page": page}),
            patch.object(ai_client, "build_answer_blocks", return_value=[]),
            patch.object(ai_client, "render_point_pages", return_value=[]),
            patch("relevance_guard.topic_frequencies", return_value=Counter()),
            patch("guide_followups.search_guides", side_effect=search),
            patch("guide_followups.proposal_chain", RunnableLambda(lambda _: "NONE")),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def ask(self, text, session):
        response = self.client.post("/chat", json={"message": text, "session_id": session})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_follow_up_retrieves_with_topic_and_receives_langchain_history(self):
        session = str(uuid4())
        self.assertEqual(self.ask("How do I configure a feed in Vision ETL?", session)["status"], "answered")
        follow = self.ask("How do I publish it?", session)
        self.assertTrue(follow["used_history"])
        self.assertEqual(follow["session_id"], session)
        self.assertIn("feed in Vision ETL", self.queries[-1][0])
        self.assertEqual(self.queries[-1][1], "ETL.pdf")
        messages = self.prompts[-1]
        self.assertEqual([message.type for message in messages], ["system", "human", "ai", "human"])
        self.assertIn("configure a feed", messages[1].content)
        self.assertNotIn("[1]", messages[2].content)
        self.assertIn("How do I publish it?", messages[-1].content)
        self.assertIn("PDF page 34", messages[-1].content)
        self.assertIn("Publish the feed", messages[-1].content)
        self.assertNotIn("Profile Setup", messages[-1].content)

    def test_sessions_new_chat_and_missing_context_are_isolated(self):
        first = str(uuid4())
        self.ask("How do I configure a feed in Vision ETL?", first)
        other = self.ask("How do I publish it?", str(uuid4()))
        self.assertEqual(other["status"], "clarification")
        self.assertEqual(len(self.prompts), 1)
        response = self.client.post("/chat", json={"message": "Hello"}).json()
        self.assertNotEqual(response["session_id"], first)
        self.assertEqual(self.client.post("/chat", json={"message": "Hi", "session_id": "invalid"}).status_code, 422)

    def test_irrelevant_follow_up_does_not_generate_or_poison_memory(self):
        session = str(uuid4())
        self.ask("How do I configure a feed in Vision ETL?", session)
        bad = self.ask("Can it predict cryptocurrency prices?", session)
        self.assertEqual(bad["status"], "not_found")
        self.assertEqual(bad["sources"], [])
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(len(self.store.sessions[session].history.messages), 2)
        independent = self.ask("Write Python code for a calculator", session)
        self.assertEqual(independent["status"], "not_found")
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.ask("How do I publish it?", session)["status"], "answered")

    def test_declined_or_failed_generation_does_not_commit_history(self):
        session = str(uuid4())
        self.decline = True
        self.assertEqual(self.ask("How do I configure a feed in Vision ETL?", session)["status"], "not_found")
        self.assertEqual(self.store.sessions[session].history.messages, [])
        self.decline, self.fail = False, True
        with self.assertLogs(level="ERROR"):
            response = self.client.post("/chat", json={"message": "How do I configure a feed in Vision ETL?", "session_id": session})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.store.sessions[session].history.messages, [])

    def test_complete_question_starts_fresh_model_context(self):
        session = str(uuid4())
        self.ask("How do I configure a feed in Vision ETL?", session)
        self.ask("How do I publish a feed in Vision ETL?", session)
        self.assertEqual(len(self.prompts[-1]), 2)
        self.assertEqual(len(self.store.sessions[session].history.messages), 2)
        self.assertIn("publish", self.store.sessions[session].anchor)

    def test_etl_setup_suggests_publishing_and_yes_continues(self):
        session = str(uuid4())
        setup = self.ask("How do I configure an ETL feed?", session)
        suggestion = setup["suggested_follow_up"]
        self.assertEqual(suggestion["prompt"], "Do you want to know how to publish it?")
        self.assertEqual(self.queries[-1][1], "ETL.pdf")
        follow_up = self.ask("Yes, please", session)
        self.assertTrue(follow_up["used_history"])
        self.assertNotIn("suggested_follow_up", follow_up)
        self.assertIn(suggestion["question"], self.prompts[-1][-1].content)

    def test_declining_the_suggestion_clears_it(self):
        session = str(uuid4())
        self.ask("How do I configure an ETL feed?", session)
        self.assertEqual(self.ask("No thanks", session)["status"], "acknowledged")
        self.assertFalse(self.store.sessions[session].pending_suggestion)


if __name__ == "__main__":
    unittest.main()
