#!/usr/bin/env python3
"""Launch the Link Downloader web app."""

import webbrowser
import uvicorn

PORT = 8899

if __name__ == "__main__":
    print(f"Starting Link Downloader on http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, log_level="warning")
