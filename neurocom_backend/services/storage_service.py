import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import requests
from fastapi import HTTPException

from neurocom_backend.utils.settings import SUPABASE_PRODUCT_BUCKET, SUPABASE_SECRET_KEY, SUPABASE_URL

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024
_session = requests.Session()


def _configuration() -> tuple[str, str, str]:
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Supabase Storage is not configured on the server")
    return SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_PRODUCT_BUCKET


def _filename(filename: str | None, content_type: str) -> str:
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
    original = Path(filename or f"product{extension}").name
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(original).stem).strip(".-") or "product"
    suffix = Path(original).suffix.lower()
    return f"{stem[:100]}{suffix if suffix in {'.jpg', '.jpeg', '.png', '.webp'} else extension}"


def upload_product_image(merchant_id: UUID, marketplace: str, filename: str | None, content_type: str, content: bytes) -> dict:
    base_url, key, bucket = _configuration()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = f"{merchant_id}/{marketplace}/{timestamp}-{uuid4()}-{_filename(filename, content_type)}"
    endpoint = f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}"
    try:
        response = _session.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": content_type, "x-upsert": "false"},
            data=content,
            timeout=(10, 60),
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach Supabase Storage ({type(exc).__name__})",
        ) from exc
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Supabase upload failed ({response.status_code})")
    public_url = f"{base_url}/storage/v1/object/public/{quote(bucket, safe='')}/{quote(path, safe='/')}"
    if not public_url.startswith("https://"):
        raise HTTPException(status_code=500, detail="Supabase public URL must use HTTPS")
    return {"path": path, "public_url": public_url, "content_type": content_type, "size": len(content)}


def delete_product_images(merchant_id: UUID, paths: list[str]) -> list[str]:
    base_url, key, bucket = _configuration()
    clean = list(dict.fromkeys(path.strip().lstrip("/") for path in paths if path.strip()))
    if not clean:
        raise HTTPException(status_code=400, detail="At least one uploaded object path is required")
    if any(not path.startswith(f"{merchant_id}/") or ".." in path.split("/") for path in clean):
        raise HTTPException(status_code=403, detail="Storage path does not belong to the authenticated merchant")
    try:
        response = _session.delete(f"{base_url}/storage/v1/object/{quote(bucket, safe='')}", headers={"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": "application/json"}, json={"prefixes": clean}, timeout=30)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Could not reach Supabase Storage") from exc
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Supabase cleanup failed ({response.status_code})")
    return clean
