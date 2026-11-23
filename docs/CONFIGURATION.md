# Configuration

All settings use the `SUNOIDA_` prefix. The backend reads `.env` from the project
root. Terminal environment variables override `.env`; defaults apply when a value
is absent. Invalid ports, URLs, numbers and ranges are rejected during startup.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUNOIDA_APP_NAME` | Sunoida Guide Assistant | API title and launcher name |
| `SUNOIDA_HOST` | 127.0.0.1 | IPv4 address on which the server listens |
| `SUNOIDA_PORT` | 8000 | First server port |
| `SUNOIDA_PORT_FALLBACK_COUNT` | 10 | Number of additional ports to try |
| `SUNOIDA_OPEN_BROWSER` | true | Open the chat after startup |
| `SUNOIDA_LOG_LEVEL` | info | Uvicorn logging level |
| `SUNOIDA_OLLAMA_URL` | http://127.0.0.1:11434 | Ollama service address |
| `SUNOIDA_OLLAMA_TIMEOUT` | 180 | Model request timeout in seconds |
| `SUNOIDA_CHAT_MODEL` | qwen2.5:0.5b | Answer-generation model |
| `SUNOIDA_EMBED_MODEL` | nomic-embed-text:v1.5 | Must match the indexed embeddings |
| `SUNOIDA_TEMPERATURE` | 0.1 | Generation variability |
| `SUNOIDA_CONTEXT_WINDOW` | 4096 | Model context size in tokens |
| `SUNOIDA_MAX_RESPONSE_TOKENS` | 450 | Output-token limit |
| `SUNOIDA_HISTORY_MAX_TURNS` | 4 | Maximum accepted question/answer pairs per chat |
| `SUNOIDA_HISTORY_MAX_CHARS` | 5000 | Total character budget for remembered messages |
| `SUNOIDA_HISTORY_TTL_SECONDS` | 1800 | Idle memory lifetime; 30 minutes by default |
| `SUNOIDA_HISTORY_MAX_SESSIONS` | 100 | Maximum in-memory conversations per backend process |
| `SUNOIDA_RETRIEVAL_TOP_K` | 4 | Maximum retrieved passages |
| `SUNOIDA_MIN_SIMILARITY` | 0.67 | Initial cosine relevance cutoff |
| `SUNOIDA_COLLECTION_NAME` | sunoida_guides_nomic_v15 | Prepared Chroma collection |
| `SUNOIDA_DOCS_DIR` | backend/docs | Source PDF directory |
| `SUNOIDA_DB_DIR` | backend/chroma_db | Persistent Chroma directory |
| `SUNOIDA_CACHE_DIR` | backend/.page_cache | Generated PNGs and image manifests |

Use `true` or `false` for booleans. Quote values containing spaces. Paths may be
absolute or relative to the project root; forward slashes also work on Windows.

For example, change the first port and leave the browser closed:

```dotenv
SUNOIDA_PORT=8080
SUNOIDA_OPEN_BROWSER=false
```

Then restart with `START_CHATBOT.cmd`. Its terminal prints the selected URL.

Increasing the similarity cutoff makes retrieval more restrictive. Similarity is
a heuristic, not an accuracy probability; the separate topic check still runs.

Model changes are checked against Ollama at startup. If using a non-default Ollama
address, start that service yourself; automatic startup is limited to the default
local address. A different embedding model or incompatible collection needs a
matching newly prepared vector index.

Only backend configuration is read from `.env`. Browser requests use relative API
paths, so the frontend follows whichever port the launcher selected.

Conversation limits bound local memory use. Expired conversations are removed on
the next request. At capacity, the oldest inactive conversation is evicted; active
requests are not evicted. History is held in the backend process and is not written
to Chroma or to disk. Use a single worker. Restarting the backend, switching guide
selection or choosing New chat starts fresh context. The browser saves transcripts
and guide selections in its chat history. Reopening a chat can reuse its answer
context while its backend session is still active.
The API returns `409` when the same conversation already has a request in progress.
