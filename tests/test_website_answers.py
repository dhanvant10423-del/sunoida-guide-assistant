"""Check website evidence, source boundaries, and fallback behavior."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from website_answers import WebsitePage, related_questions, website_fallback, website_url
from ai_client import answer_question


class WebsiteTests(unittest.TestCase):
    def test_contact_page_cannot_supply_a_product_definition(self):
        with (
            patch("ai_client.catalog", return_value={"st": {"filename": "studio.pdf", "title": "Vision Studio", "id": "st"}}),
            patch("ai_client.search_guides", return_value=[{
                "source": "studio.pdf", "page": 49, "similarity": .95,
                "text": "Support & Contact Information. For more information about Vision SupTech contact Sunoida.",
            }]),
            patch("ai_client.answer_chain") as model,
        ):
            result = answer_question("What is Vision SupTech?")
        self.assertEqual(result["status"], "not_found")
        model.invoke.assert_not_called()

    def test_external_addresses_are_rejected(self):
        for url in ["https://evil.example/", "//evil.example/", "https://sunoida.com.evil.example/", "http://sunoida.com/"]:
            self.assertIsNone(website_url(url))
        self.assertEqual(website_url("/our-profile/"), "https://sunoida.com/our-profile/")

    def test_relevant_fallback_has_real_source_and_related_questions(self):
        home = WebsitePage()
        home.feed('<a href="/our-profile/">Company Profile incorporated headquarters</a>')
        profile = WebsitePage()
        profile.feed("<title>Sunoida: Our Profile</title><p>Sunoida Solutions DMCC was incorporated in 2011 "
                     "and provides banking analytics solutions to financial institutions.</p>")
        with patch("website_answers.fetch_page", side_effect=lambda url, _: home if url.endswith(".com/") else profile):
            answer = website_fallback("When was Sunoida founded?")
        self.assertEqual(answer["answer_origin"], "website")
        self.assertIn("2011", answer["reply"])
        self.assertIn("user guides", answer["reply"])
        self.assertEqual(answer["web_sources"][0]["url"], "https://sunoida.com/our-profile/")
        self.assertGreaterEqual(len(related_questions("When was Sunoida founded?", answer)), 1)

    def test_random_question_never_fetches_website(self):
        with patch("website_answers.fetch_page") as fetch:
            answer = website_fallback("Write a poem about a cricket match", "ETL.pdf")
        fetch.assert_not_called()
        self.assertEqual(answer["status"], "out_of_scope")

    def test_ssbi_without_selected_guide_reaches_website_and_has_recommendations(self):
        home = WebsitePage()
        page = WebsitePage()
        page.feed(
            "<title>Sunoida: Vision BI Modules</title>"
            "<p>Configure and customize reports and dashboards. Self-Service BI gives "
            "you flexibility and self-reliance in reporting and analysis.</p>"
            "<p>Users can filter reports and create analyses. Self-service functions "
            "help them adapt reports to their individual needs.</p>"
        )
        question = "how to configure SSBI reports"
        with patch("website_answers.fetch_page", side_effect=lambda url, _: home if url.endswith(".com/") else page):
            result = website_fallback(question)
        self.assertEqual(result["answer_origin"], "website")
        self.assertEqual(result["web_sources"][0]["url"], "https://sunoida.com/vision-bi/self-service-bi/")
        self.assertIn("customize reports", result["reply"])
        self.assertIn("does not provide", result["reply"])
        self.assertEqual(len(related_questions(question, result)), 3)

    def test_unavailable_website_does_not_claim_to_have_found_information(self):
        with patch("website_answers.fetch_page", side_effect=httpx.ConnectError("unavailable")):
            answer = website_fallback("When was Sunoida founded?")
        self.assertEqual(answer["status"], "clarification")
        self.assertNotIn("web_sources", answer)
        self.assertIn("unavailable", answer["reply"])


if __name__ == "__main__":
    unittest.main()
