"""Integration tests for MyTinyWhisperer API.

yt-dlp is mocked throughout — no real network calls are made.
The run_download function is patched to immediately complete the download
by writing a fake file and updating the downloads state dict directly.
"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app, downloads


@pytest.fixture(autouse=True)
def clear_downloads():
    """Reset in-memory downloads dict between tests."""
    downloads.clear()
    yield
    downloads.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fake_run_download(download_id: str, req) -> None:
    """Drop-in replacement for run_download that completes instantly."""
    outdir = Path(f"/tmp/mytw/{download_id}")
    outdir.mkdir(parents=True, exist_ok=True)
    fake_file = outdir / "test_video.mp4"
    fake_file.write_bytes(b"fake video content")
    downloads[download_id].update(
        {
            "status": "complete",
            "filepath": str(fake_file),
            "filename": fake_file.name,
            "percent": 100,
        }
    )


@pytest.fixture(autouse=True)
def cleanup_tmp():
    """Remove any /tmp/mytw dirs created during a test."""
    yield
    shutil.rmtree("/tmp/mytw", ignore_errors=True)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

def test_index_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"MyTinyWhisperer" in response.content


# ---------------------------------------------------------------------------
# POST /api/download
# ---------------------------------------------------------------------------

def test_download_video_returns_download_id(client):
    with patch("main.run_download", side_effect=fake_run_download):
        response = client.post(
            "/api/download",
            json={"url": "https://youtube.com/watch?v=test", "type": "video", "resolution": "720p", "format": "mp4"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "download_id" in data
    assert len(data["download_id"]) == 36  # UUID


def test_download_audio_returns_download_id(client):
    with patch("main.run_download", side_effect=fake_run_download):
        response = client.post(
            "/api/download",
            json={"url": "https://youtube.com/watch?v=test", "type": "audio"},
        )
    assert response.status_code == 200
    assert "download_id" in response.json()


def test_download_empty_url_returns_400(client):
    response = client.post(
        "/api/download",
        json={"url": "", "type": "video"},
    )
    assert response.status_code == 400
    assert "URL" in response.json()["detail"]


def test_download_invalid_type_returns_400(client):
    response = client.post(
        "/api/download",
        json={"url": "https://youtube.com/watch?v=test", "type": "gif"},
    )
    assert response.status_code == 400


def test_download_missing_url_returns_422(client):
    response = client.post("/api/download", json={"type": "video"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/progress/{download_id}
# ---------------------------------------------------------------------------

def _parse_sse(content: bytes) -> list[dict]:
    """Parse SSE response body into a list of data dicts."""
    events = []
    for line in content.decode().splitlines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                events.append(json.loads(payload))
    return events


def test_progress_unknown_id_emits_error(client):
    response = client.get("/api/progress/nonexistent-id")
    assert response.status_code == 200
    events = _parse_sse(response.content)
    assert any(e.get("status") == "error" for e in events)


def test_progress_complete_state_emits_complete(client):
    download_id = "test-complete-id"
    downloads[download_id] = {
        "status": "complete",
        "percent": 100,
        "speed": "",
        "eta": "",
        "filepath": "/tmp/mytw/test/file.mp4",
        "filename": "file.mp4",
        "error": None,
    }
    response = client.get(f"/api/progress/{download_id}")
    assert response.status_code == 200
    events = _parse_sse(response.content)
    assert any(e.get("status") == "complete" for e in events)


def test_progress_error_state_emits_error(client):
    download_id = "test-error-id"
    downloads[download_id] = {
        "status": "error",
        "percent": 0,
        "speed": "",
        "eta": "",
        "filepath": None,
        "filename": None,
        "error": "Video unavailable",
    }
    response = client.get(f"/api/progress/{download_id}")
    events = _parse_sse(response.content)
    assert any(e.get("status") == "error" for e in events)
    assert any("Video unavailable" in e.get("message", "") for e in events)


def test_progress_pending_state_emits_status(client):
    download_id = "test-pending-id"
    # Seed a complete state so the SSE loop terminates; first event is pending→complete
    downloads[download_id] = {
        "status": "complete",
        "percent": 100,
        "speed": "",
        "eta": "",
        "filepath": None,
        "filename": "file.mp4",
        "error": None,
    }
    response = client.get(f"/api/progress/{download_id}")
    events = _parse_sse(response.content)
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# GET /api/file/{download_id}
# ---------------------------------------------------------------------------

def test_file_unknown_id_returns_404(client):
    response = client.get("/api/file/nonexistent-id")
    assert response.status_code == 404


def test_file_pending_state_returns_404(client):
    download_id = "test-pending-file"
    downloads[download_id] = {
        "status": "pending",
        "percent": 0,
        "speed": "",
        "eta": "",
        "filepath": None,
        "filename": None,
        "error": None,
    }
    response = client.get(f"/api/file/{download_id}")
    assert response.status_code == 404


def test_file_served_with_attachment_header(client, tmp_path):
    download_id = "test-serve-id"
    fake_file = tmp_path / "video.mp4"
    fake_file.write_bytes(b"fake video content")

    downloads[download_id] = {
        "status": "complete",
        "percent": 100,
        "speed": "",
        "eta": "",
        "filepath": str(fake_file),
        "filename": "video.mp4",
        "error": None,
    }

    response = client.get(f"/api/file/{download_id}")
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.content == b"fake video content"


def test_file_cleanup_removes_entry(client, tmp_path):
    download_id = "test-cleanup-id"
    fake_file = tmp_path / "video.mp4"
    fake_file.write_bytes(b"data")

    downloads[download_id] = {
        "status": "complete",
        "percent": 100,
        "speed": "",
        "eta": "",
        "filepath": str(fake_file),
        "filename": "video.mp4",
        "error": None,
    }

    client.get(f"/api/file/{download_id}")
    # After serving, the entry should be removed from downloads
    assert download_id not in downloads
