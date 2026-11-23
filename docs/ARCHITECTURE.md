# Architecture

## Document preparation

The guides were read with pypdf, split into passages, embedded with Nomic through
Ollama and stored with filename/page metadata in ChromaDB. This runtime project
uses the existing prepared index; the historical preparation scripts are not part
of the current source package.

## Answer request

1. JavaScript posts a question, random UUID conversation ID and optional selected-guide ID to `/chat`.
2. FastAPI validates the request and locks that conversation for the request.
3. A follow-up reuses the last accepted topic and its guide scope. A complete new
   question or an explicitly named product uses fresh context. Search embeds this
   resolved question, retrieves passages and calculates cosine scores.
4. A named product restricts retrieval to its guide. Weak matches and passages
   missing the question's important topics are rejected.
5. A LangChain `ChatPromptTemplate` adds approved passages, the current question
   and bounded recent LangChain messages through `MessagesPlaceholder`.
   `ChatOllama` invokes the configured local Qwen model; `StrOutputParser` reads
   the response. Follow-ups usually send the most recent question and answer to
   the model. Previous chat helps interpret questions. Guide passages supply the
   evidence.
6. The response is split into points and mapped to validated source pages.
7. Substantial embedded PDF images are extracted, filtered and cached.
8. The browser displays relevant screenshots below the answer text, with one
   image per guide page and a collapsed list of additional references.
9. Successful grounded turns enter memory; refusals, greetings and failed requests
   do not. Old citation numbers are removed from remembered answers because every
   request retrieves and numbers its own sources again.

## Modules

| Module | Responsibility |
| --- | --- |
| `config.py` | Central validated settings and project-relative paths |
| `main.py` | HTTP routes, validation, static frontend and file responses |
| `search_guides.py` | Embedding requests, product scope and vector retrieval |
| `relevance_guard.py` | Conservative topic checks and not-found/greeting replies |
| `ai_client.py` | Context assembly, Qwen calls and answer orchestration |
| `conversation.py` | LangChain message buffer, follow-up topic resolution, per-session locks, TTL and capacity |
| `source_pages.py` | Allow-listed guide catalog and full-page browsing |
| `guide_figures.py` | Embedded raster image extraction and content-based caching |
| `guide_overview.py` | Product introductions and the Data Quality workflow visual |
| `point_images.py` | Point/source metadata and sparse citations |
| `launch_chatbot.py` | Preflight checks, listening port reservation and browser launch |

## API

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` | Main frontend |
| GET | `/health` | Runtime health and answer-policy version |
| GET | `/api/guides` | Guide library metadata |
| POST | `/chat` | Guide question answering; accepts optional `session_id` UUID and returns it |
| GET | `/api/guides/{id}/pdf` | Original PDF |
| GET | `/api/guides/{id}/pages/{page}/preview` | Full-page browsing preview |
| GET | `/api/guides/{id}/pages/{page}/figures` | Extracted image metadata |
| GET | `/api/guides/{id}/pages/{page}/figures/{figure_id}` | Extracted image PNG |

Generated images are separate from the original PDFs. Chat image previews use the
figure endpoints; manually browsing a guide can still show full original pages.

## Limits

Relevance/topic matching and the small local model remain imperfect. Valid
paraphrases can be rejected and accepted answers still need source checking.
The model is not trained or fine-tuned on the PDFs. LangChain manages prompt/model
composition and message context; the existing Chroma retrieval and evidence checks
remain explicit application code. There is no LangChain agent or tool-calling loop.
Embedded raster extraction can omit vector-only diagrams and scanned pages.
Conversation memory is process-local, temporary and bounded. The launcher uses
one worker. Multiple workers or durable conversation storage would require a shared
store. Follow-up detection is an English heuristic and may require the user to name
the product/feature again; it adds no model query-rewriting call. Memory adds prompt
length, so follow-ups can run more slowly on a CPU. Small-model errors remain possible.
