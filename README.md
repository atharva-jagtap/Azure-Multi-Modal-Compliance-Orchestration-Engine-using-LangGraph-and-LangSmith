# Brand Guardian AI

Brand Guardian AI is a video compliance audit pipeline for checking YouTube content against brand or regulatory rules.

It:

- downloads a YouTube video with `yt-dlp`
- sends the video to Azure Video Indexer for transcript and OCR extraction
- retrieves relevant policy documents from Azure AI Search
- audits the content with Azure OpenAI
- exposes both a CLI flow and a FastAPI endpoint
- sends telemetry to Azure Monitor / Application Insights

## Architecture

The workflow is built with LangGraph and currently runs in two main steps:

1. `Indexer`
   - downloads the source video
   - uploads or reuses the video in Azure Video Indexer
   - waits for indexing to finish
   - extracts transcript, OCR text, and metadata

2. `Auditor`
   - embeds the transcript and OCR text
   - retrieves matching compliance rules from Azure AI Search
   - calls Azure OpenAI to generate structured compliance findings

<img width="1402" height="817" alt="Project2_Langgraph_Architecture" src="https://github.com/user-attachments/assets/573e74ea-b5d3-43f2-8acc-10434284b31a" />

## Project Structure

```text
backend/
  data/                     Source PDFs for rule indexing
  scripts/index_documents.py
  src/
    api/
      server.py             FastAPI app
      telemetry.py          Azure Monitor / OpenTelemetry setup
    graph/
      workflow.py           LangGraph workflow
      nodes.py              Indexer and auditor nodes
      state.py              Graph state schema
    services/
      video_indexer.py      Azure Video Indexer integration
main.py                     CLI runner
pyproject.toml              Python project config
.env.example                Required environment variables template
```

## Requirements

- Python 3.13 or 3.14
- `uv`
- Azure Video Indexer resource
- Azure OpenAI resource with:
  - one chat deployment
  - one embeddings deployment
- Azure AI Search index
- Application Insights connection string for telemetry
- Azure authentication for local development
  - easiest option: install Azure CLI and run `az login`

## Running the CLI Flow

The CLI runner uses the YouTube URL hardcoded in [main.py](/c:/Users/chess/Desktop/ComplainceQAPipline/main.py).

```bash
uv run python main.py
```

This will print:

- input payload
- indexing progress
- compliance status
- detected violations
- final summary

## Running the API

Start the FastAPI server:

```bash
uv run uvicorn backend.src.api.server:app --reload
```

Useful endpoints:

- `GET /health`
- `GET /docs`
- `POST /audit`

Example request:

```bash
curl -X POST "http://127.0.0.1:8000/audit" \
  -H "Content-Type: application/json" \
  -d "{\"video_url\":\"https://youtu.be/dT7S75eYhcQ\"}"
```

## Indexing Source Documents

Policy documents can be indexed into Azure AI Search with:

```bash
uv run python backend/scripts/index_documents.py
```

Make sure your Azure AI Search configuration is present in `.env` before running it.

## Observability

Telemetry is configured in [telemetry.py]

The app sends traces and logs to Azure Monitor / Application Insights and now sets an explicit service identity

## Working pieces:

- FastAPI server startup
- Azure Monitor telemetry setup
- Azure Video Indexer upload and polling
- Azure AI Search retrieval
- Azure OpenAI embeddings and chat wiring
