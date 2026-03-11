# Link Downloader

Web-based multi-part download manager for [link-scraper](https://github.com/DavidMSPT/link-scraper) data. Handles split-file downloads (multiple .rar parts) with parallel downloading and real-time progress.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python run.py
```

Opens in your browser at `http://localhost:8899`.

## Features

- Browse and search games from scraped data
- Filter by file host (DataNodes, FuckingFast, etc.)
- Parallel multi-part downloads (3 concurrent files)
- Real-time progress via WebSocket
- Auto-fetches latest game data from GitHub
- Magnet link support (opens in default torrent client)
- Skips already-downloaded files

## Screenshot

The app shows a game list on the left with search/filter. Select a game, pick a host, click Download. Progress is shown at the bottom with per-file and overall tracking.
