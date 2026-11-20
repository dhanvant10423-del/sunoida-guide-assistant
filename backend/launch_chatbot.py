"""Start this project's Python, model service and current frontend together."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid
import webbrowser
from config import settings

BACKEND = Path(__file__).resolve().parent
PROJECT = BACKEND.parent
LOCAL_HTTP = build_opener(ProxyHandler({}))
REQUIRED_MODELS = tuple(dict.fromkeys((settings.chat_model, settings.embed_model)))


def read_json(url, timeout=2):
    with LOCAL_HTTP.open(url, timeout=timeout) as response:
        return json.load(response)


def check_ollama(start_if_needed=True):
    try:
        tags = read_json(f"{settings.ollama_url}/api/tags")
    except (OSError, URLError, ValueError):
        if not start_if_needed:
            raise RuntimeError("Open Ollama, then run START_CHATBOT.cmd again.")
        if settings.ollama_url != "http://127.0.0.1:11434":
            raise RuntimeError("The configured Ollama service is unavailable. Start it at SUNOIDA_OLLAMA_URL and try again.")
        executable = shutil.which("ollama")
        if not executable:
            candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
            executable = str(candidate) if candidate.is_file() else None
        if not executable:
            raise RuntimeError("Ollama was not found. Open or install Ollama, then try again.")
        logs = BACKEND / "data"
        logs.mkdir(exist_ok=True)
        with (logs / "ollama-startup.log").open("ab") as log:
            subprocess.Popen(
                [executable, "serve"], stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        print("Starting Ollama...", flush=True)
        deadline = time.monotonic() + 30
        while True:
            try:
                tags = read_json(f"{settings.ollama_url}/api/tags")
                break
            except (OSError, URLError, ValueError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Ollama did not start. Open Ollama manually and try again.")
                time.sleep(0.5)
    available = {item.get("name") for item in tags.get("models", [])}
    missing = [model for model in REQUIRED_MODELS if model not in available]
    if missing:
        commands = "\n".join(f"  ollama pull {model}" for model in missing)
        raise RuntimeError(f"These local models need to be downloaded first:\n{commands}")


def preflight(start_ollama=True):
    required = (
        "index.html", "assets/app.js", "assets/inline-pages.js",
        "assets/inline-chat.html", "assets/styles.css", "assets/favicon.svg",
    )
    for relative in required:
        if not (PROJECT / "frontend" / relative).is_file():
            raise RuntimeError(f"A frontend file is missing: frontend/{relative}. Extract the complete update.")
    try:
        import uvicorn
        from main import app
        from search_guides import COLLECTION_NAME, database
        from source_pages import public_guides
    except ImportError as error:
        raise RuntimeError(f"A backend package is missing: {error}. Use this project's backend Python environment.") from error
    check_ollama(start_if_needed=start_ollama)
    guides = public_guides()
    if not any(guide["available"] for guide in guides):
        raise RuntimeError("No readable guide PDFs were found in backend/docs.")
    try:
        collection = database().get_collection(name=COLLECTION_NAME, embedding_function=None)
        passages = collection.count()
    except Exception as error:
        raise RuntimeError("The guide index could not be opened. Run prepare_chunks.py and build_chroma.py using backend/.venv.") from error
    if not passages:
        raise RuntimeError("The guide index is empty. Run build_chroma.py before starting the chatbot.")
    print(f"Ready: {sum(guide['available'] for guide in guides)} guides, {passages} indexed passages.", flush=True)
    return app, uvicorn


def bind_available_port(first=None, last=None):
    first = settings.port if first is None else first
    last = first + settings.port_fallback_count if last is None else last
    # Reserve the actual listening socket so another process cannot take this port
    # between the check and startup. Existing servers are never stopped or reused.
    for port in range(first, last + 1):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((settings.host, port))
            return listener
        except OSError:
            listener.close()
    raise RuntimeError(f"Ports {first} through {last} are in use. Close an older chatbot terminal and try again.")


def open_when_ready(server, url):
    deadline = time.monotonic() + 45
    while not server.started:
        if server.should_exit or time.monotonic() >= deadline:
            return
        time.sleep(0.1)
    try:
        if not webbrowser.open(url):
            print(f"Open this link in your browser: {url}", flush=True)
    except Exception:
        print(f"Open this link in your browser: {url}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check installed files, models and index without starting services")
    parser.add_argument("--no-browser", action="store_true", help="Start the app without opening a browser")
    args = parser.parse_args()
    os.chdir(BACKEND)
    print(f"{settings.app_name} - LANGCHAIN CHAT MEMORY", flush=True)
    print(f"Project: {PROJECT}", flush=True)
    app, uvicorn = preflight(start_ollama=not args.check)
    if args.check:
        print("Startup checks passed.", flush=True)
        return 0
    listener = bind_available_port()
    port = listener.getsockname()[1]
    browser_host = "127.0.0.1" if settings.host == "0.0.0.0" else settings.host
    url = f"http://{browser_host}:{port}/assets/inline-chat.html?run={uuid.uuid4().hex}"
    print(f"\nChatbot: {url}", flush=True)
    if port != settings.port:
        print(f"Port {settings.port} is occupied. This copy will run on port {port}.", flush=True)
    print("Keep this window open. Press Ctrl+C here to stop this copy.\n", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=port, workers=1, log_level=settings.log_level))
    if settings.open_browser and not args.no_browser:
        threading.Thread(target=open_when_ready, args=(server, url), daemon=True).start()
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
    return 0 if server.started else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nChatbot stopped.")
    except Exception as error:
        print(f"\nCould not start: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
