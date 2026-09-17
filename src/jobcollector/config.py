"""Загрузка конфигурации поиска: JSON нативно, YAML при наличии PyYAML."""

from __future__ import annotations

import json
from pathlib import Path

from .models import LocationSpec, SearchSpec, TransportConfig


def _spec_from_dict(data: dict) -> SearchSpec:
    transport_raw = data.get("transport") or {}
    return SearchSpec(
        sources=list(data.get("sources") or []),
        queries=list(data.get("queries") or []),
        locations=[LocationSpec(**loc) for loc in (data.get("locations") or [])],
        posted_within_days=data.get("posted_within_days"),
        exclude_titles=list(data.get("exclude_titles") or []),
        max_results_per_search=int(data.get("max_results_per_search") or 100),
        max_pages_per_search=int(data.get("max_pages_per_search") or 3),
        max_detail_requests_per_run=int(data.get("max_detail_requests_per_run") or 20),
        fetch_descriptions=bool(data.get("fetch_descriptions", True)),
        transport=TransportConfig(
            request_delay_seconds=float(transport_raw.get("request_delay_seconds") or 2.0),
            timeout_seconds=float(transport_raw.get("timeout_seconds") or 30.0),
            max_retries=int(transport_raw.get("max_retries") or 2),
            indeed_domain=transport_raw.get("indeed_domain") or "www.indeed.com",
        ),
    )


def load_spec(path: Path) -> SearchSpec:
    text = Path(path).read_text(encoding="utf-8")
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return _spec_from_dict(json.loads(text))
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # optional dependency
        except ImportError as exc:
            raise RuntimeError(
                "YAML-конфиг требует PyYAML (pip install pyyaml) "
                "или используйте JSON-конфиг") from exc
        return _spec_from_dict(yaml.safe_load(text))
    raise ValueError(f"неподдерживаемый формат конфига: {suffix}")
