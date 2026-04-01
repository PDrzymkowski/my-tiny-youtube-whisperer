import asyncio
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask


downloads: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Path("static").mkdir(exist_ok=True)
    Path("/tmp/mytw").mkdir(exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


class DownloadRequest(BaseModel):
    url: str
    type: str  # "video" | "audio"
    resolution: str = "1080p"  # "1080p"|"720p"|"480p"|"360p"
    format: str = "mp4"  # "mp4"|"webm"|"mkv"


def run_download(download_id: str, req: DownloadRequest) -> None:
    outdir = f"/tmp/mytw/{download_id}"

    def progress_hook(d: dict) -> None:
        if d["status"] == "downloading":
            raw = d.get("_percent_str", "0%").strip().rstrip("%")
            try:
                pct = float(raw)
            except ValueError:
                pct = 0.0
            downloads[download_id].update(
                {
                    "status": "downloading",
                    "percent": pct,
                    "speed": d.get("_speed_str", "").strip(),
                    "eta": d.get("_eta_str", "").strip(),
                }
            )
        elif d["status"] == "finished":
            downloads[download_id]["filepath"] = d["filename"]

    if req.type == "audio":
        ydl_opts: dict = {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": f"{outdir}/%(title)s.%(ext)s",
            "progress_hooks": [progress_hook],
        }
    else:
        height = int(req.resolution.rstrip("p"))
        ydl_opts = {
            "format": (
                f"bestvideo[height<={height}]+bestaudio"
                f"/best[height<={height}]"
            ),
            "merge_output_format": req.format,
            "outtmpl": f"{outdir}/%(title)s.%(ext)s",
            "progress_hooks": [progress_hook],
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([req.url])

        files = list(Path(outdir).iterdir())
        if files:
            filepath = str(files[0])
            filename = files[0].name
            downloads[download_id].update(
                {
                    "status": "complete",
                    "filepath": filepath,
                    "filename": filename,
                    "percent": 100,
                }
            )
        else:
            downloads[download_id].update(
                {"status": "error", "error": "No file produced by yt-dlp"}
            )
    except Exception as e:
        downloads[download_id].update({"status": "error", "error": str(e)})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.post("/api/download")
async def start_download(req: DownloadRequest) -> dict:
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="URL is required")
    if req.type not in ("video", "audio"):
        raise HTTPException(status_code=400, detail="type must be 'video' or 'audio'")

    download_id = str(uuid.uuid4())
    Path(f"/tmp/mytw/{download_id}").mkdir(parents=True, exist_ok=True)

    downloads[download_id] = {
        "status": "pending",
        "percent": 0,
        "speed": "",
        "eta": "",
        "filepath": None,
        "filename": None,
        "error": None,
    }

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, lambda: run_download(download_id, req))

    return {"download_id": download_id}


@app.get("/api/progress/{download_id}")
async def progress(download_id: str) -> EventSourceResponse:
    async def event_generator():
        while True:
            state = downloads.get(download_id)
            if state is None:
                yield {
                    "data": json.dumps(
                        {"status": "error", "message": "Unknown download ID"}
                    )
                }
                break

            status = state["status"]
            if status == "complete":
                yield {
                    "data": json.dumps(
                        {"status": "complete", "filename": state["filename"]}
                    )
                }
                break
            elif status == "error":
                yield {
                    "data": json.dumps(
                        {"status": "error", "message": state.get("error", "Unknown error")}
                    )
                }
                break
            else:
                yield {
                    "data": json.dumps(
                        {
                            "status": status,
                            "percent": state["percent"],
                            "speed": state["speed"],
                            "eta": state["eta"],
                        }
                    )
                }

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/file/{download_id}")
async def serve_file(download_id: str) -> FileResponse:
    state = downloads.get(download_id)
    if not state or state["status"] != "complete":
        raise HTTPException(status_code=404, detail="File not ready or not found")

    filepath = state["filepath"]
    filename = state["filename"]

    def cleanup() -> None:
        shutil.rmtree(f"/tmp/mytw/{download_id}", ignore_errors=True)
        downloads.pop(download_id, None)

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream",
        background=BackgroundTask(cleanup),
    )
