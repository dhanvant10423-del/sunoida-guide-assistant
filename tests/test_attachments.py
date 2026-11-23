"""Exercise attachment parsing and chat continuity without model downloads."""

import base64
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import attachments
import main


def upload(name, content):
    return {"name": name, "data": base64.b64encode(content).decode()}


def sample_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    text = DecodedStreamObject()
    text.set_data(b"BT /F1 18 Tf 72 700 Td (Reference ID BI-42) Tj ET")
    page.replace_contents(text)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_word_text_is_extracted(self):
        document = BytesIO()
        with ZipFile(document, "w") as archive:
            archive.writestr(
                "word/document.xml",
                f'<w:document xmlns:w="{attachments.WORD_NAMESPACE[1:-1]}">'
                "<w:body><w:p><w:r><w:t>Service status: Pending</w:t></w:r></w:p></w:body>"
                "</w:document>",
            )
        file = attachments.read_attachment(attachments.Upload(**upload("status.docx", document.getvalue())))
        self.assertEqual(file.text, "Service status: Pending")

    def test_pdf_text_is_extracted_with_page_label(self):
        file = attachments.read_attachment(attachments.Upload(**upload("reference.pdf", sample_pdf())))
        self.assertIn("PDF page 1\nReference ID BI-42", file.text)

    def test_scope_locked_and_screenshot_available_in_follow_up(self):
        image = BytesIO()
        Image.new("RGB", (160, 80), "white").save(image, format="PNG")
        payload = {
            "message": "Describe the screenshot",
            "source_id": "BI",
            "session_id": str(uuid4()),
            "attachments": [upload("screen.png", image.getvalue())],
        }
        reply = SimpleNamespace(message=SimpleNamespace(content="The screenshot shows a white background."))
        with (
            patch.object(main, "get_document", side_effect=lambda source: {"filename": f"{source}.pdf"}),
            patch.object(attachments, "_guide_context", return_value=([], [])),
            patch.object(attachments.ollama, "chat", return_value=reply) as model,
        ):
            first = self.client.post("/chat/attachments", json=payload)
            follow_up = {"message": "What color is it?", "source_id": "BI", "session_id": payload["session_id"]}
            rejected = self.client.post("/chat", json={**follow_up, "source_id": "ETL"})
            following = self.client.post("/chat", json=follow_up)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(following.status_code, 200)
        self.assertTrue(following.json()["used_history"])
        self.assertEqual(model.call_count, 2)
        for call in model.call_args_list:
            self.assertEqual(call.kwargs["model"], attachments.settings.vision_model)
            self.assertTrue(call.kwargs["messages"][-1]["images"][0].startswith(b"\xff\xd8"))

    def test_invalid_uploads_get_actionable_errors(self):
        for file, status in [
            (upload("unknown.exe", b"sample"), 415),
            (upload("broken.png", b"sample"), 422),
            (upload("broken.docx", b"sample"), 422),
            (upload("bad.txt", b"\xff"), 422),
        ]:
            with self.subTest(file=file["name"]):
                response = self.client.post("/chat/attachments", json={"message": "Read this", "attachments": [file]})
                self.assertEqual(response.status_code, status)


if __name__ == "__main__":
    unittest.main()
