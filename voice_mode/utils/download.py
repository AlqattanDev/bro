"""Download utilities with progress indicators."""

import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Union
import click


def detect_progress_style() -> str:
    """Auto-detect best progress style based on environment."""
    if os.environ.get('CI'):
        return 'verbose'  # CI environment
    if not sys.stdout.isatty():
        return 'verbose'  # Not a terminal
    if os.environ.get('VOICEMODE_PROGRESS_STYLE'):
        return os.environ['VOICEMODE_PROGRESS_STYLE']
    return 'bar'  # Default to progress bar


def format_size(bytes_size: int) -> str:
    """Format bytes into human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


def download_with_progress(
    url: str,
    destination: Union[str, Path],
    description: Optional[str] = None,
    style: str = "auto",
    quiet: bool = False
) -> bool:
    """
    Download file with progress indicator.

    Args:
        url: URL to download from
        destination: Where to save the file
        description: Label for the progress bar
        style: Progress indicator style (auto, bar, spinner, verbose, quiet)
        quiet: Suppress all output

    Returns:
        True if successful, False otherwise
    """
    if quiet:
        style = 'quiet'
    elif style == 'auto':
        style = detect_progress_style()

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not description:
        description = f"Downloading {destination.name}"

    try:
        # Open the URL and get headers
        response = urllib.request.urlopen(url)
        total_size = int(response.headers.get('Content-Length', 0))

        if style == 'quiet':
            # Silent download
            with open(destination, 'wb') as f:
                while chunk := response.read(8192):
                    f.write(chunk)
            return True

        elif style == 'verbose':
            # Verbose mode for CI/logging
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting download: {destination.name}")
            print(f"URL: {url}")
            if total_size > 0:
                print(f"Size: {format_size(total_size)}")

            downloaded = 0
            start_time = time.time()
            last_print = 0

            with open(destination, 'wb') as f:
                while chunk := response.read(8192):
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Print progress every 5% or 5 seconds
                    current_time = time.time()
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        if percent - last_print >= 5 or current_time - start_time >= 5:
                            speed = downloaded / (current_time - start_time)
                            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Progress: {percent:.0f}% ({format_size(downloaded)} / {format_size(total_size)}) - {format_size(speed)}/s")
                            last_print = percent
                    elif current_time - start_time >= 5:
                        speed = downloaded / (current_time - start_time)
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Downloaded: {format_size(downloaded)} - {format_size(speed)}/s")
                        start_time = current_time

            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Download complete: {destination.name}")
            return True

        elif total_size == 0 or style == 'spinner':
            # Unknown size - use spinner
            with click.progressbar(
                label=description,
                length=None,
                show_percent=False,
                show_pos=True
            ) as bar:
                downloaded = 0
                with open(destination, 'wb') as f:
                    while chunk := response.read(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        bar.update(len(chunk))

            click.echo(f" ✓ Downloaded {format_size(downloaded)}")
            return True

        else:  # style == 'bar' or default
            # Known size - use progress bar
            # Add size info to label
            size_str = format_size(total_size)
            full_label = f"{description} ({size_str})"

            with click.progressbar(
                length=total_size,
                label=full_label,
                show_eta=True,
                show_percent=True,
                show_pos=False,  # Disable raw byte position
                width=40,
                fill_char='█',
                empty_char='░'
            ) as bar:
                with open(destination, 'wb') as f:
                    while chunk := response.read(8192):
                        f.write(chunk)
                        bar.update(len(chunk))

            click.echo(" ✓ Complete")
            return True

    except urllib.error.HTTPError as e:
        if not quiet:
            click.echo(f"\n❌ Download failed: HTTP {e.code} {e.reason}", err=True)
        return False
    except urllib.error.URLError as e:
        if not quiet:
            click.echo(f"\n❌ Download failed: {e.reason}", err=True)
        return False
    except KeyboardInterrupt:
        if not quiet:
            click.echo(f"\n❌ Download interrupted by user", err=True)
        # Clean up partial file
        if destination.exists():
            destination.unlink()
        return False
    except Exception as e:
        if not quiet:
            click.echo(f"\n❌ Download failed: {e}", err=True)
        return False


async def download_with_progress_async(
    url: str,
    destination: Union[str, Path],
    description: Optional[str] = None,
    style: str = "auto",
    quiet: bool = False
) -> bool:
    """
    Async wrapper for download_with_progress.

    Uses sync download in thread to avoid blocking event loop.
    """
    import asyncio
    return await asyncio.to_thread(
        download_with_progress,
        url, destination, description, style, quiet
    )