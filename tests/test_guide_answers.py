"""Check overview routing, answer order, and screenshot selection."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from ai_client import answer_question, ensure_procedure_lead
from conversation import Conversation, title_for
from point_images import guide_figure_pages


class GuideAnswerTests(unittest.TestCase):
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

    def test_direct_answer_precedes_numbered_steps(self):
        formatted = ensure_procedure_lead("Follow these steps:\n\n1. Open Feed Configuration.\n2. Select a feed.")
        self.assertTrue(formatted.startswith("Open Feed Configuration.\n\n1."))
        self.assertIn("2. Select a feed.", formatted)
        self.assertEqual(title_for("How do I configure an ETL feed?"), "Configure an ETL feed")

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
