"""Cloud folder port (Google Drive API): the online shared folder the approver uses from the browser."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..core.mirror import RemoteFile


class CloudFolder(Protocol):
    """Minimal file operations on a cloud drive. Vendor-neutral; implemented in adapters/gdrive.py."""

    def find_folder(self, name: str) -> str | None:
        """Id of a folder with this name in the user's root (My Drive), if any."""
        ...

    def list_children(self, folder_id: str) -> list[RemoteFile]:
        """Files and folders directly inside a folder (not trashed)."""
        ...

    def get(self, file_id: str) -> RemoteFile:
        ...

    def download(self, file_id: str, dest: Path) -> None:
        ...

    def upload(self, parent_id: str, name: str, src: Path) -> str:
        """Create a new file; returns its id."""
        ...

    def update(self, file_id: str, src: Path) -> None:
        """Replace the content of an existing file."""
        ...

    def create_folder(self, parent_id: str, name: str) -> str:
        ...

    def move(self, file_id: str, new_parent_id: str, old_parent_id: str) -> None:
        ...

    def trash(self, file_id: str) -> None:
        """Move to the bin (recoverable for 30 days), never a hard delete."""
        ...
