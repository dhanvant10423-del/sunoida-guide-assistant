"""Check overview routing, answer order, and screenshot selection."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from ai_client import answer_question, ensure_procedure_lead
from conversation import Conversation, title_for
from guide_confirmation import GuideDecision, confirmation_claim, is_yes_no_question, supported_decision
from guide_features import connector_add_action, feature_check
from point_images import guide_figure_pages
from search_guides import question_source


class GuideAnswerTests(unittest.TestCase):
    def test_yes_no_questions_are_distinguished_from_procedure_requests(self):
        for question in (
            "Does the Widget Menu provides options to clear the screen of all the widgets",
            "Is the Widget Menu unable to clear all widgets?",
            "Could you tell me whether a monitor is available?",
        ):
            self.assertTrue(is_yes_no_question(question), question)
        for question in (
            "How do I clear all widgets?",
            "Can you explain how to check if an ETL feed has run?",
            "Would you show me the steps for configuring a connector?",
        ):
            self.assertFalse(is_yes_no_question(question), question)

    def test_yes_no_opening_uses_the_validated_verdict_and_source(self):
        passages = [{"index": 2, "text": "The Widget Menu provides options to clear the screen of all the widgets."}]
        quote = "provides options to clear the screen of all the widgets"
        yes = GuideDecision(evidence=quote, explanation="Yes, you can clear the widgets. [1]", verdict="yes")
        self.assertEqual(supported_decision(yes, passages), "Yes. You can clear the widgets. [2]")
        no = GuideDecision(evidence=quote, explanation="The Widget Menu lets you clear all widgets.", verdict="no")
        self.assertEqual(supported_decision(no, passages), "No. The Widget Menu lets you clear all widgets. [2]")
        self.assertIsNone(supported_decision(yes.model_copy(update={"verdict": "unknown"}), passages))
        self.assertIsNone(supported_decision(yes.model_copy(update={"evidence": "Delete every saved dashboard report"}), passages))
        self.assertIsNone(supported_decision(no.model_copy(update={"explanation": "The guide does not provide enough evidence."}), passages))

    def test_negative_ability_inverts_the_answer_to_the_positive_claim(self):
        question, negated = confirmation_claim("Is the Widget Menu unable to clear all widgets?")
        self.assertEqual(question, "Is the Widget Menu able to clear all widgets?")
        self.assertTrue(negated)
        passages = [{"index": 1, "text": "The Widget Menu enables users to clear all widgets."}]
        decision = GuideDecision(
            evidence=passages[0]["text"], explanation="The Widget Menu can clear all widgets.", verdict="yes",
        )
        self.assertEqual(supported_decision(decision, passages, negated), "No. The Widget Menu can clear all widgets. [1]")

    def test_connector_add_question_with_short_guide_name(self):
        document = {"id": "etl", "filename": "etl.pdf", "title": "Vision ETL", "short": "ETL"}
        pages = {
            12: ("Creating a New Connector\nClick Add to create a new connector.\n"
                 "Mandatory Fields: Country, LE Book, Connector ID, Connection Name, Endpoint Type, Connector Type."),
            17: ("Click on Save button to save the connector. Approved connectors become available for: "
                 "Feed configuration, ETL execution."),
        }
        question = "Does the Add button create a new connector in ETL"
        with (
            patch("ai_client.catalog", return_value={"etl": document}),
            patch("source_pages.catalog", return_value={"etl": document}),
            patch("guide_features.read_page_text", side_effect=lambda _, page: pages[page]),
            patch("guide_features.reference_for", side_effect=lambda _, page, index, *args: {"page": page, "index": index}),
            patch("ai_client.search_guides") as search,
        ):
            self.assertEqual(question_source(question), "etl.pdf")
            self.assertIsNone(question_source("What does loading mean in ETL processing?"))
            result = answer_question(question)
            locked = answer_question(question, source="dq.pdf")
        search.assert_not_called()
        self.assertTrue(result["reply"].startswith("Yes, **Add** starts a new connector"))
        self.assertIn("click **Save** to store the connector", result["reply"])
        self.assertIn("After approval", result["reply"])
        self.assertEqual([ref["page"] for ref in result["sources"]], [12, 17])
        self.assertEqual(locked["status"], "clarification")

    def test_connector_add_variants_require_connector_context(self):
        self.assertEqual(connector_add_action("DoEs clicking the “Add” icon create a new source connector?"), "create")
        self.assertEqual(connector_add_action("Can I use Add to create a connector in Vision ETL?"), "create")
        self.assertEqual(connector_add_action("What does Add do in ETL Connector Configuration?"), "describe")
        self.assertEqual(connector_add_action("Does the Add button save a new connector?"), "save")
        self.assertIsNone(connector_add_action("Does Add create a new connector query in ETL?"))
        self.assertIsNone(connector_add_action("What does the Add button do in ETL?"))

    def test_monitor_question_with_repeated_word_uses_selected_guide(self):
        document = {"id": "etl", "filename": "etl.pdf", "title": "Vision ETL", "short": "ETL"}
        pages = {
            6: ("Monitor Dashboard\nThe Dashboard provides an overview of ETL engines.\n"
                "Widget Menu\nThe selected widgets are saved as the default view."),
            4: "ETL Console\nThe console has two primary sections: Dashboard and Operations.",
        }
        question = "does this app have have a monitoring page ?"
        with (
            patch("ai_client.catalog", return_value={"etl": document}),
            patch("guide_features.read_page_text", side_effect=lambda _, page: pages[page]),
            patch("guide_features.reference_for", side_effect=lambda _, page, index, *args: {"page": page, "index": index}),
            patch("ai_client.search_guides") as search,
        ):
            result = answer_question(question, source="etl.pdf")
        search.assert_not_called()
        self.assertTrue(result["reply"].startswith(
            "Yes, **Vision ETL** has a monitoring page called **Monitor Dashboard**. It provides"
        ))
        self.assertIn("**ETL Console → Dashboard**", result["reply"])
        self.assertIn("save them as your default view", result["reply"])
        self.assertEqual([ref["page"] for ref in result["sources"]], [6, 4])

    def test_monitor_question_uses_discussed_guide_and_starts_a_new_topic(self):
        document = {"id": "dq", "filename": "dq.pdf", "title": "Vision AI Data Quality", "short": "DQ"}
        conversation = Conversation(source="dq.pdf", anchor="What is the trust score?")
        with (
            patch("ai_client.catalog", return_value={"dq": document}),
            patch("guide_features.read_page_text", return_value=(
                "The Data Monitor shows table trends. It combines the results of your approved rules "
                "(by table, by column and by version) with checks for data timeliness, volume, "
                "schema changes and data pattern shift. Use it to identify which column or rule is responsible, "
                "and see exactly what changed since the previous run. Tables are ranked by rule pass rate.\n"
                "SIDEBAR Monitor\n"
            )),
            patch("guide_features.reference_for", return_value={"page": 92, "index": 1}),
        ):
            result = answer_question("Is there a monitoring page in this app?", conversation=conversation)
        self.assertTrue(result["reply"].startswith(
            "Yes, **Vision AI Data Quality** has a monitoring page called **Data Monitor**. It shows"
        ))
        self.assertTrue(result["used_history"])
        self.assertIn("**approved-rule results**", result["reply"])
        self.assertIn("since the previous run", result["reply"])
        self.assertIn("Open **Monitor** in the sidebar.", result["reply"])
        self.assertEqual(conversation.anchor, "monitoring")

    def test_feature_presence_requires_a_product_and_keeps_the_feature_topic(self):
        self.assertEqual(feature_check("Does this app have a crypto monitoring page?"), ("crypto monitoring", None))
        with patch("ai_client.catalog", return_value={}):
            result = answer_question("Does this app have a monitoring page?")
        self.assertEqual(result["status"], "clarification")
        self.assertIn("Which Sunoida product", result["reply"])

    def test_other_screen_presence_checks_use_feature_terms_in_selected_guide(self):
        document = {"id": "etl", "filename": "etl.pdf", "title": "Vision ETL", "short": "ETL"}
        conversation = Conversation(source="etl.pdf", anchor="How do I publish a feed?")
        with (
            patch("ai_client.catalog", return_value={"etl": document}),
            patch("ai_client.search_guides", return_value=[]) as search,
        ):
            result = answer_question("Does this app have an interstellar navigation page?", conversation=conversation)
        self.assertEqual(search.call_args.args[0], "interstellar navigation")
        self.assertEqual(search.call_args.kwargs["source"], "etl.pdf")
        self.assertEqual(result["status"], "not_found")
        self.assertIn("Vision ETL", result["reply"])
        self.assertEqual(conversation.anchor, "How do I publish a feed?")

    def test_generic_overview_uses_current_guide_and_keeps_context(self):
        document = {"id": "dq", "filename": "dq.pdf", "title": "Vision AI Data Quality", "short": "DQ"}
        pages = {
            3: "Vision AI Data Quality measures data quality. It profiles every column.",
            4: ("1.2 How it works: from source to decision\n1 Connect a source. Description\n"
                "2 Choose tables. Description\nChoose rules. Description\nRun. Description\n"
                "Explore the result. Description\nDecide. Description\n1.3 The two headline scores"),
        }
        conversation = Conversation(scope="dq.pdf")
        with (
            patch("ai_client.catalog", return_value={"dq": document}),
            patch("guide_overview.read_page_text", side_effect=lambda _, page: pages[page]),
            patch("guide_overview.reference_for", side_effect=lambda _, page, index, *args: {"page": page, "index": index}),
            patch("ai_client.search_guides") as search,
        ):
            result = answer_question("Explain about this application", source="dq.pdf", conversation=conversation)
        search.assert_not_called()
        self.assertTrue(result["reply"].startswith("Vision AI Data Quality measures"))
        self.assertEqual(result["chat_title"], "Vision AI Data Quality overview")
        self.assertEqual(result["workflow"]["steps"][3], "Run")
        self.assertEqual(conversation.source, "dq.pdf")

    def test_application_overview_without_guide_describes_the_assistant(self):
        with patch("ai_client.catalog", return_value={}):
            answer = answer_question("What does this app do?")
        self.assertIn("Sunoida User Guide Assistant", answer["reply"])
        self.assertEqual(answer["sources"], [])

    def test_connector_opening_names_task_without_repeating_first_action(self):
        steps = "1. Open the ETL Connector Config module. [1]\n2. Click Add."
        for previous in ("", "Follow these steps:\n\n", "**Open the ETL Connector Config module.**\n\n"):
            with self.subTest(previous=previous):
                formatted = ensure_procedure_lead(previous + steps, "How do I setup a data source connector?", "Vision ETL")
                self.assertTrue(formatted.startswith("Here are the steps to set up a data source connector in Vision ETL.\n\n1."))
                self.assertEqual(formatted.count("Open the ETL Connector Config module."), 1)
                self.assertIn("2. Click Add.", formatted)
        self.assertEqual(title_for("How do I configure an ETL feed?"), "Configure an ETL feed")

    def test_procedure_keeps_useful_context_and_leaves_prose_answers_alone(self):
        reply = "A Checker must authorize the feed.\n\n1. Click Publish.\n2. Wait for approval."
        formatted = ensure_procedure_lead(reply, "How do I publish a feed in Vision ETL?", "Vision ETL")
        self.assertTrue(formatted.startswith("Here are the steps to publish a feed in Vision ETL.\n\nA Checker"))
        simple = "The Data Trust Score measures governance evidence. [1]"
        self.assertEqual(ensure_procedure_lead(simple, "What is the Data Trust Score?"), simple)
        numbered = "1. The DQ Health Index.\n2. The Data Trust Score."
        self.assertEqual(ensure_procedure_lead(numbered, "What are the two scores?"), numbered)

    def test_figure_selection_reuses_mapped_figures_and_checks_other_sources(self):
        references = [{"index": index, "document_id": "guide", "page": index} for index in range(1, 4)]
        points = [{"pages": [{"document_id": "guide", "page": 2, "figures": [{"figure_id": "shared"}]}]}]
        with patch("point_images.extract_figures", side_effect=[
            [{"figure_id": "shared"}, {"figure_id": "original"}], [],
        ]) as extract:
            found = guide_figure_pages(points, references)
        self.assertEqual([(item["page"], item["figures"][0]["figure_id"]) for item in found],
                         [(2, "shared"), (1, "original")])
        self.assertEqual(extract.call_count, 2)


if __name__ == "__main__":
    unittest.main()
