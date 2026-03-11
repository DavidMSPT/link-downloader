#!/usr/bin/env python3
"""Web-based multi-part download manager."""

import asyncio
import json
import os
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# --- Config ---
DEFAULT_SOURCE = "https://raw.githubusercontent.com/DavidMSPT/link-scraper/master/output/fitgirl-repacks.json"
DEFAULT_OUTPUT = str(Path.home() / "Downloads" / "link-downloader")
CONCURRENT_DOWNLOADS = 3

# --- State ---
active_downloads: dict[str, dict] = {}  # download_id -> status
connected_clients: list[WebSocket] = []

HOST_NAMES = {
    "datanodes.to": "DataNodes",
    "fuckingfast.co": "FuckingFast",
    "gofile.io": "Gofile",
    "buzzheavier.com": "Buzzheavier",
    "vikingfile.com": "VikingFile",
    "pixeldrain.com": "PixelDrain",
    "mediafire.com": "MediaFire",
    "mega.nz": "Mega",
    "1fichier.com": "1Fichier",
    "filecrypt.cc": "FileCrypt",
    "1337x.to": "1337x",
    "rutor.info": "RuTor",
    "tapochek.net": "Tapochek",
}


def get_host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").removeprefix("www.")


def get_filename(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    name = Path(path).name
    if parsed.fragment:
        name = unquote(parsed.fragment)
    return name or "download"


def group_uris_by_host(uris: list[str]) -> dict[str, list[str]]:
    groups = {}
    for uri in uris:
        if uri.startswith("magnet:"):
            groups.setdefault("magnet", []).append(uri)
            continue
        host = get_host(uri)
        if host:
            groups.setdefault(host, []).append(uri)
    return groups


def safe_dirname(title: str) -> str:
    return "".join(c if c.isalnum() or c in " -_.()" else "_" for c in title)


async def broadcast(msg: dict):
    for ws in connected_clients[:]:
        try:
            await ws.send_json(msg)
        except Exception:
            connected_clients.remove(ws)


async def download_file(client: httpx.AsyncClient, url: str, dest: Path, download_id: str, file_index: int, total_files: int):
    """Download a single file and broadcast progress."""
    filename = dest.name

    if dest.exists() and dest.stat().st_size > 0:
        await broadcast({
            "type": "file_progress",
            "downloadId": download_id,
            "file": filename,
            "fileIndex": file_index,
            "totalFiles": total_files,
            "status": "skipped",
        })
        return True

    try:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)

                    await broadcast({
                        "type": "file_progress",
                        "downloadId": download_id,
                        "file": filename,
                        "fileIndex": file_index,
                        "totalFiles": total_files,
                        "downloaded": downloaded,
                        "total": total,
                        "status": "downloading",
                    })

        await broadcast({
            "type": "file_progress",
            "downloadId": download_id,
            "file": filename,
            "fileIndex": file_index,
            "totalFiles": total_files,
            "downloaded": total,
            "total": total,
            "status": "done",
        })
        return True

    except Exception as e:
        if dest.exists():
            dest.unlink()
        await broadcast({
            "type": "file_progress",
            "downloadId": download_id,
            "file": filename,
            "fileIndex": file_index,
            "totalFiles": total_files,
            "status": "error",
            "error": str(e),
        })
        return False


async def download_game_task(download_id: str, title: str, uris: list[str], output_dir: str):
    """Download all parts for a game with parallel downloads."""
    out = Path(output_dir) / safe_dirname(title)
    out.mkdir(parents=True, exist_ok=True)

    active_downloads[download_id] = {"title": title, "status": "downloading", "progress": 0}

    await broadcast({
        "type": "download_start",
        "downloadId": download_id,
        "title": title,
        "totalFiles": len(uris),
    })

    semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)
    client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=600.0))

    async def bounded_download(url, index):
        async with semaphore:
            dest = out / get_filename(url)
            return await download_file(client, url, dest, download_id, index, len(uris))

    tasks = [bounded_download(url, i) for i, url in enumerate(uris)]
    results = await asyncio.gather(*tasks)

    await client.aclose()

    success = all(results)
    active_downloads[download_id]["status"] = "done" if success else "error"

    await broadcast({
        "type": "download_complete",
        "downloadId": download_id,
        "title": title,
        "success": success,
        "path": str(out),
    })


# --- API ---

@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/games")
async def get_games(source: str = DEFAULT_SOURCE):
    async with httpx.AsyncClient(timeout=30.0) as client:
        if source.startswith("http"):
            resp = await client.get(source, follow_redirects=True)
            data = resp.json()
        else:
            with open(source) as f:
                data = json.load(f)

    games = []
    for dl in data.get("downloads", []):
        hosts = group_uris_by_host(dl["uris"])
        host_info = {}
        for host, urls in hosts.items():
            host_info[host] = {
                "name": HOST_NAMES.get(host, host),
                "count": len(urls),
            }
        games.append({
            "title": dl["title"],
            "fileSize": dl.get("fileSize", ""),
            "uploadDate": dl.get("uploadDate", ""),
            "hosts": host_info,
            "uris": dl["uris"],
        })

    return {"name": data.get("name", "Downloads"), "games": games}


@app.post("/api/download")
async def start_download(body: dict):
    title = body["title"]
    uris = body["uris"]
    host = body["host"]
    output_dir = body.get("outputDir", DEFAULT_OUTPUT)

    # Filter URIs by host
    if host == "magnet":
        filtered = [u for u in uris if u.startswith("magnet:")]
    else:
        filtered = [u for u in uris if get_host(u) == host]

    if not filtered:
        return {"error": "No URIs for selected host"}

    download_id = f"{safe_dirname(title)}_{host}_{id(uris)}"

    asyncio.create_task(download_game_task(download_id, title, filtered, output_dir))

    return {"downloadId": download_id, "files": len(filtered)}


@app.get("/api/config")
async def get_config():
    return {"outputDir": DEFAULT_OUTPUT, "source": DEFAULT_SOURCE}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
