# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install

# Run development server
poetry run uvicorn main:app --reload

# Run all tests
poetry run pytest

# Run a single test
poetry run pytest tests/test_api.py::test_index_returns_html
```

## Architecture

Single-file FastAPI app (`main.py`) with a static HTML frontend (`static/index.html`). No database — download state is kept in an in-memory dict (`downloads: dict[str, dict]`) that resets on restart.

**Download flow:**
1. `POST /api/download` → validates request, generates UUID, launches `run_download()` in a thread via `run_in_executor`, returns `{download_id}`
2. `GET /api/progress/{id}` → SSE stream that polls `downloads[id]` every 500ms until status is `complete` or `error`
3. `GET /api/file/{id}` → serves the finished file as a browser download via `FileResponse`, then cleans up `/tmp/mytw/{id}/` with a `BackgroundTask`

**`run_download()`** is a synchronous function (runs in a thread pool). It builds yt-dlp options, hooks into progress events to update `downloads[id]`, and sets `status: complete` or `status: error` when done. For audio it uses FFmpegExtractAudio postprocessor; for video it merges best video+audio streams.

**Frontend** (`static/index.html`) is a single self-contained file — Tailwind CDN, Inter font, vanilla JS. It has a built-in EN/PL i18n system (`i18n` object + `setLang()`). All translatable strings use `data-i18n` attributes. Progress updates come via `EventSource`; on completion `window.location.href` triggers the browser download.

**Tests** (`tests/test_api.py`) use FastAPI's `TestClient` with `unittest.mock.patch` to replace `run_download` with a fake that immediately writes a file and sets `status: complete`. For file-serving tests, `downloads` is seeded directly to avoid threading timing issues.