# MyTinyYoutubeWhisperer

A minimal web app for downloading YouTube videos and audio, built with FastAPI and yt-dlp.

## Features

- Download video in mp4, webm, or mkv at up to 1080p
- Extract audio as MP3 at 192 kbps
- Real-time progress bar via SSE
- Clean, single-page UI — no frontend build step

## Prerequisites

- Python 3.13+
- [Poetry](https://python-poetry.org/)
- [ffmpeg](https://ffmpeg.org/) (required for audio extraction and video merging)

## Setup

```bash
git clone https://github.com/PDrzymkowski/my-tiny-youtube-whisperer.git
cd my-tiny-youtube-whisperer
poetry install
```

## Run

```bash
poetry run uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Tests

```bash
poetry run pytest
```

## Tech stack

FastAPI · yt-dlp · Tailwind CSS · Server-Sent Events
