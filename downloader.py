#!/usr/bin/env python3
"""Multi-part download manager for scraped game data.

Reads JSON from link-scraper, lets you pick a game and host,
then downloads all parts in parallel.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt, IntPrompt

console = Console()

# Map hostnames to friendly names
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
}


def get_host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").removeprefix("www.")


def get_filename(url: str) -> str:
    """Extract filename from URL."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    name = Path(path).name
    # For URLs with fragment filenames (fuckingfast style)
    if parsed.fragment:
        name = unquote(parsed.fragment)
    return name or "download"


def group_uris_by_host(uris: list[str]) -> dict[str, list[str]]:
    """Group URIs by their host."""
    groups = {}
    for uri in uris:
        if uri.startswith("magnet:"):
            groups.setdefault("magnet", []).append(uri)
            continue
        host = get_host(uri)
        if host:
            groups.setdefault(host, []).append(uri)
    return groups


def download_file(client: httpx.Client, url: str, dest: Path, progress, task_id) -> bool:
    """Download a single file with progress tracking."""
    try:
        with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()

            total = int(response.headers.get("content-length", 0))
            if total:
                progress.update(task_id, total=total)

            with open(dest, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=65536):
                    f.write(chunk)
                    progress.update(task_id, advance=len(chunk))

        return True
    except Exception as e:
        console.print(f"  [red]Error downloading {dest.name}: {e}[/red]")
        return False


def download_game(uris: list[str], output_dir: Path):
    """Download all parts for a game from the given URIs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\nDownloading {len(uris)} file(s) to [cyan]{output_dir}[/cyan]\n")

    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        client = httpx.Client(timeout=httpx.Timeout(30.0, read=300.0))

        for uri in uris:
            filename = get_filename(uri)
            dest = output_dir / filename

            if dest.exists():
                console.print(f"  [yellow]Skipping {filename} (already exists)[/yellow]")
                continue

            task_id = progress.add_task(f"  {filename[:50]}", total=None)
            success = download_file(client, uri, dest, progress, task_id)

            if not success and dest.exists():
                dest.unlink()  # Clean up partial file

        client.close()

    console.print(f"\n[green]Done! Files saved to {output_dir}[/green]")


def load_data(source: str) -> dict:
    """Load game data from a local file or remote URL."""
    if source.startswith("http://") or source.startswith("https://"):
        console.print(f"Fetching data from [cyan]{source}[/cyan]...")
        resp = httpx.get(source, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    else:
        with open(source) as f:
            return json.load(f)


def interactive_select(data: dict, output_base: Path, host_filter: str | None):
    """Interactive mode: pick a game and host, then download."""
    downloads = data.get("downloads", [])
    if not downloads:
        console.print("[red]No downloads found in data.[/red]")
        return

    # Show games
    table = Table(title=f"{data.get('name', 'Downloads')} ({len(downloads)} games)")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Size", justify="right")
    table.add_column("Hosts")

    for i, dl in enumerate(downloads):
        hosts = group_uris_by_host(dl["uris"])
        host_names = [HOST_NAMES.get(h, h) for h in hosts if h != "magnet"]
        if "magnet" in hosts:
            host_names.append("Magnet")
        table.add_row(
            str(i + 1),
            dl["title"][:60],
            dl.get("fileSize", "?"),
            ", ".join(host_names),
        )

    console.print(table)

    # Pick game
    choice = IntPrompt.ask(
        "\nSelect a game to download",
        choices=[str(i) for i in range(1, len(downloads) + 1)],
    )
    game = downloads[choice - 1]
    console.print(f"\n[bold]{game['title']}[/bold]")
    console.print(f"Size: {game.get('fileSize', 'Unknown')}")

    # Group by host
    hosts = group_uris_by_host(game["uris"])

    # Pick host
    host_list = list(hosts.keys())
    console.print("\nAvailable hosts:")
    for i, host in enumerate(host_list):
        name = HOST_NAMES.get(host, host)
        count = len(hosts[host])
        console.print(f"  {i + 1}. {name} ({count} file{'s' if count > 1 else ''})")

    if host_filter:
        # Auto-select matching host
        matching = [h for h in host_list if host_filter.lower() in h.lower()]
        if matching:
            selected_host = matching[0]
            console.print(f"\nAuto-selected: {HOST_NAMES.get(selected_host, selected_host)}")
        else:
            console.print(f"[red]No host matching '{host_filter}'[/red]")
            return
    else:
        host_choice = IntPrompt.ask(
            "Select host",
            choices=[str(i) for i in range(1, len(host_list) + 1)],
        )
        selected_host = host_list[host_choice - 1]

    uris = hosts[selected_host]

    if selected_host == "magnet":
        console.print(f"\n[cyan]Magnet link:[/cyan]")
        for uri in uris:
            console.print(uri)
        return

    # Sanitize game title for folder name
    safe_title = "".join(c if c.isalnum() or c in " -_.()" else "_" for c in game["title"])
    output_dir = output_base / safe_title

    download_game(uris, output_dir)


def batch_download(data: dict, output_base: Path, host_filter: str):
    """Batch mode: download all games from a specific host."""
    downloads = data.get("downloads", [])
    console.print(f"Batch downloading {len(downloads)} games via {host_filter}...\n")

    for dl in downloads:
        hosts = group_uris_by_host(dl["uris"])
        matching = [h for h in hosts if host_filter.lower() in h.lower()]

        if not matching:
            console.print(f"[yellow]Skipping {dl['title'][:50]} (no {host_filter} links)[/yellow]")
            continue

        uris = hosts[matching[0]]
        safe_title = "".join(c if c.isalnum() or c in " -_.()" else "_" for c in dl["title"])
        output_dir = output_base / safe_title

        console.print(f"\n[bold]{dl['title'][:60]}[/bold] ({dl.get('fileSize', '?')})")
        download_game(uris, output_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Multi-part download manager for scraped game data."
    )
    parser.add_argument(
        "source",
        help="Path to JSON file or URL (e.g. raw.githubusercontent.com/...)",
    )
    parser.add_argument(
        "-o", "--output",
        default="downloads",
        help="Output directory (default: downloads/)",
    )
    parser.add_argument(
        "--host",
        help="Filter/auto-select host (e.g. datanodes, fuckingfast)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Download all games (non-interactive)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available games and exit",
    )

    args = parser.parse_args()
    data = load_data(args.source)
    output_base = Path(args.output)

    if args.list:
        downloads = data.get("downloads", [])
        for i, dl in enumerate(downloads, 1):
            hosts = group_uris_by_host(dl["uris"])
            host_names = [HOST_NAMES.get(h, h) for h in hosts if h != "magnet"]
            console.print(f"{i:3}. {dl['title'][:60]:60s} {dl.get('fileSize', '?'):>10s}  {', '.join(host_names)}")
        return

    if args.batch:
        if not args.host:
            console.print("[red]--batch requires --host (e.g. --host datanodes)[/red]")
            return
        batch_download(data, output_base, args.host)
    else:
        interactive_select(data, output_base, args.host)


if __name__ == "__main__":
    main()
