"""Subida opcional a YouTube con la API oficial (OAuth 2.0, vídeo privado)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from clutchreel.utils.paths import appdata_dir

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
ProgressFn = Callable[[float, str], None]


class YouTubeError(Exception):
    pass


def token_path() -> Path:
    return appdata_dir() / "youtube_token.json"


def is_configured(client_secrets: str) -> bool:
    return bool(client_secrets) and Path(client_secrets).exists()


def _credentials(client_secrets: str):  # type: ignore[no-untyped-def]
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover
        raise YouTubeError("Faltan las librerías de Google. Ejecuta Iniciar.bat para instalarlas.") from exc
    creds = None
    tp = token_path()
    if tp.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
        except (ValueError, OSError):
            creds = None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo refrescar el token de YouTube: %s", exc)
            creds = None
    if not creds or not creds.valid:
        if not is_configured(client_secrets):
            raise YouTubeError("No hay credenciales de YouTube configuradas (client_secrets.json). Mira el README.")
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
        try:
            tp.write_text(creds.to_json(), encoding="utf-8")
        except OSError as exc:
            log.warning("No se pudo guardar el token: %s", exc)
    return creds


def upload_video(
    client_secrets: str,
    video: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "private",
    thumbnail: Path | None = None,
    progress: ProgressFn | None = None,
) -> str:
    """Sube el vídeo y devuelve su ID. Lanza :class:`YouTubeError`."""
    if not video.exists():
        raise YouTubeError("El vídeo a subir no existe.")
    creds = _credentials(client_secrets)
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:  # pragma: no cover
        raise YouTubeError("Faltan las librerías de Google. Ejecuta Iniciar.bat.") from exc
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:30], "categoryId": "20"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True)
    try:
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress:
                progress(float(status.progress()), "Subiendo a YouTube…")
        video_id = str(response.get("id", ""))
        if thumbnail and thumbnail.exists():
            try:
                service.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
            except HttpError as exc:
                log.warning("Miniatura no subida: %s", exc)
        return video_id
    except HttpError as exc:
        try:
            detail = json.loads(exc.content.decode("utf-8"))["error"]["message"]
        except Exception:  # noqa: BLE001
            detail = str(exc)
        raise YouTubeError(f"YouTube rechazó la subida: {detail}") from exc
