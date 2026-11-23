# Sunoida Guide Assistant

A local PDF question-answering application for Sunoida product guides. It uses
Ollama for embeddings and answers, ChromaDB for retrieval, and FastAPI to serve
the browser interface. LangChain connects Qwen to recent conversation messages.
Screenshots are extracted from the original PDFs.

## Run the existing project

Double-click **START_CHATBOT.cmd**. If the Python environment is missing, the
launcher installs it and the required packages before opening the chatbot.
Keep its terminal open and use the browser tab it opens. The launcher selects
another port when the configured port is occupied.
Press **Ctrl+C** in that terminal to stop that copy.

Run a startup check from Command Prompt without opening a browser:

```bat
START_CHATBOT.cmd --check
```

This project has been checked on Windows with Python 3.14, six guide PDFs and
1,129 indexed passages. Local Ollama inference does not need an API key.

## First-time setup

1. Clone this repository or download its source ZIP.
2. Install Python 3.14 with the Windows Python launcher and install Ollama if
   they are missing.
3. If Ollama does not already have the two models, open Ollama and run these
   commands in Command Prompt.

   ~~~bat
   ollama pull qwen2.5:0.5b
   ollama pull nomic-embed-text:v1.5
   ~~~

4. Copy the six original guide PDFs into **backend/docs** and the prepared
   Chroma index into **backend/chroma_db**. Use the PDFs and index from an existing
   working installation or from the full local chatbot bundle. Keep the guide
   filenames as they appear in the bundle so they still match the index.
5. Run **START_CHATBOT.cmd** and use the browser tab it opens. On the first run
   it installs the locked Python dependencies and creates the local settings file.

The GitHub repository contains the source code. The full local chatbot bundle
contains the six PDFs and prepared index. Setup requires an internet connection
for packages and any Ollama models you need to download.

## Project layout

```text
.
|-- .env                    # Your local settings; excluded from Git
|-- .env.example            # Shareable configuration template
|-- .gitignore
|-- .editorconfig
|-- README.md
|-- requirements.txt        # Direct application dependencies
|-- requirements.lock.txt   # Snapshot of the tested Windows environment
|-- START_CHATBOT.cmd
|-- SETUP_CHATBOT.cmd
|-- backend/
|   |-- config.py           # Loads and validates settings
|   |-- main.py             # API routes and frontend serving
|   |-- ai_client.py        # Answer generation and orchestration
|   |-- conversation.py     # Bounded conversation memory and follow-up context
|   |-- search_guides.py    # Chroma search and similarity scoring
|   |-- relevance_guard.py  # Topic checks and unsupported-question handling
|   |-- guide_figures.py    # Embedded screenshot extraction and caching
|   |-- source_pages.py     # Guide catalog, PDF access and page browsing
|   |-- point_images.py     # Answer-point/source-image mapping
|   |-- launch_chatbot.py   # Startup checks and server launch
|   |-- docs/              # Local source PDFs
|   |-- chroma_db/         # Local vector database
|   |-- .page_cache/       # Generated previews; safe to regenerate
|   `-- .venv/             # Local Python environment
|-- frontend/
|   |-- index.html
|   `-- assets/             # JavaScript, CSS, icons and fresh entry page
|-- tests/                  # Configuration and integration checks
`-- docs/                   # Architecture and configuration
```

## Configuration

Edit the project-root **.env**, then restart the launcher. Settings in the terminal
take precedence over the file. Relative data paths are resolved from the project
root, even when you start from another folder.

```dotenv
SUNOIDA_CHAT_MODEL=qwen2.5:0.5b
SUNOIDA_EMBED_MODEL=nomic-embed-text:v1.5
SUNOIDA_PORT=8000
SUNOIDA_MIN_SIMILARITY=0.67
```

Changing the embedding model requires a matching rebuilt index. Changing the chat
model does not change stored embeddings. See [configuration](docs/CONFIGURATION.md).

`.env` is read by the backend and is not served to the browser. Keep real credentials
out of `.env.example`; it is the template intended for sharing.

## Request flow

Question + conversation ID -> FastAPI -> resolve follow-up context -> Nomic
embedding -> Chroma retrieval -> relevance checks -> LangChain prompt with recent
messages -> Qwen answer -> point/page mapping -> extracted screenshots -> browser.

## Continuing a conversation

Ask "How do I configure an ETL feed in Vision ETL?", then "How do I publish it?"
in the same chat. The second question uses the earlier topic and recent messages,
while retrieving and checking fresh guide evidence. No extra model call is used
to rewrite the question. LangChain's `ChatPromptTemplate`, `MessagesPlaceholder`,
message objects and `ChatOllama` handle the model conversation.

Click **New chat** to open a blank conversation. Use the guide picker in the
message box to search one guide or all guides. Changing the guide starts fresh
answer context, and the transcript stays visible.

The **Chats** sidebar saves up to 30 recent conversations with up to 40 messages
each in the current browser. Open one to restore its messages and selected guide.
The server's answer context is available while its session is active. Stopped
or failed requests use a new session so unseen answers cannot affect the next
question.

Ask "Show me step 2" to revisit that numbered step from the last procedure. From
there, ask "What is the next step?" to continue through the same procedure.

After a supported answer, the chatbot can offer a related question with evidence
in the same guide. Click the suggestion or reply **Yes** to continue. The prompt
depends on the guide and topic.

Only grounded, successful answers enter memory. Greetings, refusals and errors
do not replace the last accepted topic. A complete new question starts a new
topic; follow-up cues such as "it", "that", "explain step 2" or "what next" reuse
the current topic. Explicitly naming a product starts fresh retrieval.

Memory holds up to four accepted question/answer pairs, capped at 5,000 characters.
It expires after 30 minutes without activity, can be evicted when the store fills,
and clears when the server restarts. Keep one backend worker, as the launcher does.
This is temporary conversation context, not permanent chat storage or model
training. See [configuration](docs/CONFIGURATION.md) to change the limits.

Rejected questions return a fixed not-found message with no sources or images.
These conservative checks can decline valid paraphrases and do not guarantee
factual correctness. Screenshots are embedded raster images; vector-only figures,
whole-page scans and small/decorative images may be omitted.

See [architecture](docs/ARCHITECTURE.md) for module responsibilities.

## Verification

From the project root:

```bat
backend\.venv\Scripts\python.exe -m unittest discover -s tests -v
START_CHATBOT.cmd --check
```

Unit tests do not require a running model service. The launcher check needs Ollama,
the configured models, PDFs and prepared index. FastAPI's interactive API reference
is at `/docs` on the port printed by the launcher.

`requirements.txt` lists direct dependencies. `requirements.lock.txt` captures the
tested full environment, and setup prefers that snapshot when present. Developers
updating dependencies should review and refresh both files together.

## Sharing the source

Keep `.env`, `.venv`, PDF guides, Chroma data and generated caches outside source
control. The `.gitignore` covers their default locations. Preserve these folders
when applying an update: merge matching source files into the existing project.

The application runs locally. Public deployment requires its own hosting setup.
