"""Check .env loading, validation and configuration wiring without model calls."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))

from config import PROJECT_DIR, Settings
from pydantic import ValidationError


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("SUNOIDA_")}
        self.environment = patch.dict(os.environ, environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_defaults_preserve_existing_models_and_data_paths(self):
        settings = Settings(_env_file=None)
        self.assertEqual(settings.chat_model, "qwen2.5:0.5b")
        self.assertEqual(settings.embed_model, "nomic-embed-text:v1.5")
        self.assertEqual(settings.docs_dir, (PROJECT_DIR / "backend/docs").resolve())
        self.assertEqual(settings.db_dir, (PROJECT_DIR / "backend/chroma_db").resolve())

    def test_env_file_is_loaded_and_typed(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("SUNOIDA_PORT=8123\nSUNOIDA_MIN_SIMILARITY=0.73\nSUNOIDA_OPEN_BROWSER=false\n", encoding="utf-8")
            settings = Settings(_env_file=env_file)
            self.assertEqual(settings.port, 8123)
            self.assertEqual(settings.min_similarity, 0.73)
            self.assertFalse(settings.open_browser)

    def test_environment_overrides_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("SUNOIDA_PORT=8123\n", encoding="utf-8")
            os.environ["SUNOIDA_PORT"] = "8124"
            self.assertEqual(Settings(_env_file=env_file).port, 8124)

    def test_relative_paths_do_not_depend_on_terminal_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                settings = Settings(_env_file=None, docs_dir=Path("backend/docs"))
                self.assertEqual(settings.docs_dir, (PROJECT_DIR / "backend/docs").resolve())
            finally:
                os.chdir(previous)

    def test_invalid_settings_fail_early(self):
        invalid = [
            {"port": 0}, {"port": 65536}, {"port": 65530, "port_fallback_count": 10},
            {"min_similarity": 1.1}, {"min_similarity": float("nan")},
            {"host": "invalid-host"}, {"ollama_url": "file:///tmp/model"},
            {"ollama_url": "http://user:password@localhost:11434"},
            {"ollama_url": "http://localhost:bad"}, {"ollama_url": "http://localhost:11434/api"},
            {"max_response_tokens": 2048, "context_window": 1024},
        ]
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, **values)

    def test_custom_models_and_boundary_port(self):
        settings = Settings(_env_file=None, chat_model="other:latest", port=65535, port_fallback_count=0)
        self.assertEqual(settings.chat_model, "other:latest")
        self.assertEqual(settings.port, 65535)


class ConfigurationWiringTests(unittest.TestCase):
    def test_runtime_modules_use_central_settings(self):
        from config import settings
        import search_guides
        import source_pages
        import launch_chatbot
        import main
        self.assertEqual(search_guides.EMBED_MODEL, settings.embed_model)
        self.assertEqual(search_guides.MIN_SIMILARITY, settings.min_similarity)
        self.assertEqual(search_guides.DB_DIR, settings.db_dir)
        self.assertEqual(source_pages.DOCS_DIR, settings.docs_dir)
        self.assertEqual(source_pages.CACHE_DIR, settings.cache_dir)
        self.assertEqual(set(launch_chatbot.REQUIRED_MODELS), {settings.chat_model, settings.embed_model})
        self.assertEqual(main.app.title, settings.app_name)

    def test_api_still_works_and_does_not_serve_env(self):
        from fastapi.testclient import TestClient
        import main
        with TestClient(main.app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/").headers["cache-control"], "no-store")
            self.assertEqual(client.get("/.env").status_code, 404)
            self.assertEqual(client.post("/chat", json={"message": "Hello!"}).json()["status"], "greeting")


if __name__ == "__main__":
    unittest.main()
