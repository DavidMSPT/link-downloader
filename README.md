# Link Downloader

Multi-part download manager that works with [link-scraper](https://github.com/DavidMSPT/link-scraper) output. Handles split-file downloads (multiple .rar parts) that tools like Hydra can't manage.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Interactive mode (pick a game and host)
```bash
# From local JSON
python downloader.py output/fitgirl-repacks.json

# From remote URL (auto-updated by GitHub Actions)
python downloader.py https://raw.githubusercontent.com/DavidMSPT/link-scraper/master/output/fitgirl-repacks.json
```

### List available games
```bash
python downloader.py data.json --list
```

### Auto-select a host
```bash
python downloader.py data.json --host datanodes
python downloader.py data.json --host fuckingfast
```

### Batch download all games
```bash
python downloader.py data.json --batch --host datanodes -o /mnt/games/
```

## Features

- Downloads all parts of a multi-part game from a chosen host
- Skips already-downloaded files (resume support)
- Progress bars with speed and ETA
- Fetches JSON from local file or remote URL
- Interactive game/host selection or batch mode
