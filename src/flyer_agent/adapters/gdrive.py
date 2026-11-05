"""Google Drive API adapter (CloudFolder port). The agent acts as the folder owner via OAuth (desktop flow).

Setup (once): Google Cloud project with the Drive API enabled, OAuth client of type "Desktop app",
its JSON saved as `credentials.json` in the project root. The first run opens the browser to sign in;
the token is cached in `.secrets/google-token.json` (gitignored) and refreshed automatically.

A service account is not used: it has no storage of its own and cannot create files in a My Drive folder.
"""

from __future__ import annotations

import io
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.mirror import RemoteFile

SCOPES = ["https://www.googleapis.com/auth/drive"]  # full access: the PDFs are uploaded by people, not by the app
FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = "id, name, mimeType, md5Checksum, modifiedTime"
mimetypes.add_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
mimetypes.add_type("text/markdown", ".md")


def credentials(client_secrets: Path, token_path: Path) -> Any:
    """OAuth user credentials: cached token, refreshed when expired, or a browser sign-in the first time."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES) if token_path.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not client_secrets.exists():
            raise SystemExit(f"manca {client_secrets}: crea un client OAuth 'Desktop app' e scarica il JSON "
                             "(README, sezione Google Drive)")
        creds = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES).run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    token_path.chmod(0o600)
    return creds


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDrive:
    """CloudFolder implementation on Drive API v3."""

    def __init__(self, creds: Any):
        from googleapiclient.discovery import build

        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    @staticmethod
    def _remote(f: dict) -> RemoteFile:
        mod = datetime.fromisoformat(f["modifiedTime"]).timestamp() if f.get("modifiedTime") else 0.0  # py3.11+: "Z" ok
        return RemoteFile(id=f["id"], name=f["name"], is_folder=f.get("mimeType") == FOLDER_MIME,
                          md5=f.get("md5Checksum"), modified=mod)

    def find_folder(self, name: str) -> str | None:
        res = self.svc.files().list(
            q=f"name = '{_q(name)}' and mimeType = '{FOLDER_MIME}' and 'root' in parents and trashed = false",
            fields="files(id)", pageSize=10).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    def list_children(self, folder_id: str) -> list[RemoteFile]:
        out: list[RemoteFile] = []
        token = None
        while True:
            res = self.svc.files().list(q=f"'{_q(folder_id)}' in parents and trashed = false",
                                        fields=f"nextPageToken, files({FIELDS})", pageSize=1000,
                                        pageToken=token).execute()
            out += [self._remote(f) for f in res.get("files", [])]
            token = res.get("nextPageToken")
            if not token:
                return out

    def get(self, file_id: str) -> RemoteFile:
        return self._remote(self.svc.files().get(fileId=file_id, fields=FIELDS).execute())

    def download(self, file_id: str, dest: Path) -> None:
        from googleapiclient.http import MediaIoBaseDownload

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, self.svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.part")
        tmp.write_bytes(buf.getvalue())
        tmp.replace(dest)

    def _media(self, src: Path) -> Any:
        from googleapiclient.http import MediaFileUpload

        mime = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
        return MediaFileUpload(str(src), mimetype=mime, resumable=src.stat().st_size > 5_000_000)

    def upload(self, parent_id: str, name: str, src: Path) -> str:
        f = self.svc.files().create(body={"name": name, "parents": [parent_id]}, media_body=self._media(src),
                                    fields="id").execute()
        return str(f["id"])

    def update(self, file_id: str, src: Path) -> None:
        self.svc.files().update(fileId=file_id, media_body=self._media(src), fields="id").execute()

    def create_folder(self, parent_id: str, name: str) -> str:
        f = self.svc.files().create(body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
                                    fields="id").execute()
        return str(f["id"])

    def move(self, file_id: str, new_parent_id: str, old_parent_id: str) -> None:
        self.svc.files().update(fileId=file_id, addParents=new_parent_id, removeParents=old_parent_id,
                                fields="id").execute()

    def trash(self, file_id: str) -> None:
        self.svc.files().update(fileId=file_id, body={"trashed": True}, fields="id").execute()
