"""Desktop notifications (macOS). Best effort: silently does nothing elsewhere or on failure."""

from __future__ import annotations

import shutil
import subprocess
import sys


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str) -> None:
    """Show a macOS notification banner."""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return
    try:
        subprocess.run(["osascript", "-e", f'display notification "{_esc(message)}" with title "{_esc(title)}"'],
                       check=False, timeout=10, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass
