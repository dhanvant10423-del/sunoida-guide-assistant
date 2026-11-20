import logging
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from config import settings
from conversation import ConversationBusyError, store

from ai_client import answer_question
from search_guides import GuideIndexError
from source_pages import get_document, public_guides, render_page
from guide_figures import extract_figures, figure_path

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
app = FastAPI(title=settings.app_name, version="2.3.2")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.middleware("http")
async def fresh_frontend(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or (path.startswith("/assets/") and path.endswith((".html", ".js", ".css"))):
        response.headers["Cache-Control"] = "no-store"
    return response


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    source_id: str | None = Field(default=None, max_length=40)
    session_id: UUID | None = None


@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "mode": "local", "guide_count": len(public_guides()), "layout": "figures-only-4", "answer_policy": "guide-only-v2", "conversation": "langchain-memory-v5"}


@app.get("/api/guides")
def guides():
    return {"guides": public_guides()}


@app.get("/api/guides/{document_id}/pdf")
def guide_pdf(document_id: str):
    try:
        document = get_document(document_id)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(
        document["path"], media_type="application/pdf",
        filename=document["filename"], content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/guides/{document_id}/pages/{page_number}/preview")
def guide_page(document_id: str, page_number: int, size: Literal["thumb", "full"] = Query("thumb")):
    try:
        image_path = render_page(document_id, page_number, size)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    except Exception as error:
        logging.exception("Could not render guide page")
        raise HTTPException(422, "This PDF page could not be rendered. Try opening the original PDF.") from error
    return FileResponse(image_path, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/guides/{document_id}/pages/{page_number}/figures")
def guide_figures(document_id: str, page_number: int):
    try:
        return {"figures": extract_figures(document_id, page_number)}
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(404, str(error)) from error
    except Exception as error:
        logging.exception("Could not inspect guide images")
        raise HTTPException(422, "The images on this guide page could not be read.") from error


@app.get("/api/guides/{document_id}/pages/{page_number}/figures/{figure_id}")
def guide_figure(document_id: str, page_number: int, figure_id: str):
    try:
        image_path = figure_path(document_id, page_number, figure_id)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(404, str(error)) from error
    except Exception as error:
        logging.exception("Could not extract guide image")
        raise HTTPException(422, "This guide image could not be extracted.") from error
    return FileResponse(image_path, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@app.post("/chat")
def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(400, "Please enter a question.")
    source = None
    if request.source_id:
        try:
            source = get_document(request.source_id)["filename"]
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
    try:
        session_id = str(request.session_id or uuid4())
        with store.use(session_id, scope=source) as conversation:
            result = answer_question(message, source=source, conversation=conversation)
        return {**result, "session_id": session_id}
    except ConversationBusyError as error:
        raise HTTPException(409, str(error)) from error
    except GuideIndexError as error:
        raise HTTPException(503, str(error)) from error
    except ConnectionError as error:
        raise HTTPException(503, "Ollama is not available. Open the Ollama application and try again.") from error
    except Exception as error:
        logging.exception("Local guide assistant request failed")
        raise HTTPException(502, "The local AI could not finish the answer. Check the backend terminal and try again.") from error
