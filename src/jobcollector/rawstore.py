"""Raw-store: сжатые исходные ответы, без секретов, до любой нормализации."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

SECRET_RX = re.compile(
    r"(api[_-]?key|authorization|set-cookie|cookie|token|password)=([^&\s]*)",
    re.IGNORECASE)


def redact(text: str) -> str:
    return SECRET_RX.sub(r"\1=<redacted>", text)


def save_raw(root: Path, source: str, doc) -> str:
    """RawDocument → data/raw/{source}/{date}/{request_id}.json.gz; возвращает ref."""
    day_dir = Path(root) / "raw" / source / doc.fetched_at[:10]
    day_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "request_id": doc.request_id,
        "url": redact(doc.url),
        "fetched_at": doc.fetched_at,
        "status": doc.status,
        "mime": doc.mime,
        "transport": getattr(doc, "transport", "http"),
        "content": redact(doc.content or ""),
    }
    path = day_dir / f"{doc.request_id}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return f"raw/{source}/{doc.fetched_at[:10]}/{path.name}"
