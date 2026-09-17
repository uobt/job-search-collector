"""Дедупликация: ключ площадки, сильные и слабые межплощадочные связи.

Сильная связь — одинаковая нормализованная исходная ссылка отклика или
совпадение requisition/job ID исходного ATS. Слабая — компания+должность+город
без сильного признака: только кандидат на дубль, не слияние.
"""

from __future__ import annotations

import re
import urllib.parse

STRIP_PARAMS = ("utm_*", "ref", "from", "trk", "li", "currentJobId", "vjk", "jk")


def normalize_url_key(url: str | None) -> str | None:
    """URL → канонический ключ: схема-agnostic хост + путь + выжившие параметры."""
    if not url:
        return None
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.netloc or "").lower()
    path = parts.path or "/"
    kept = []
    for key, value in sorted(urllib.parse.parse_qsl(parts.query or "")):
        if any(re.fullmatch(pat.replace("*", ".*"), key) for pat in STRIP_PARAMS):
            continue
        kept.append(f"{key}={value}")
    query = ("?" + "&".join(kept)) if kept else ""
    return f"{host}{path}{query}"


def company_slug(name: str | None) -> str | None:
    if not name:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:80] or None


def title_slug(title: str | None) -> str | None:
    if not title:
        return None
    stop = {"a", "an", "the", "of", "(", ")", "–", "-"}
    words = [w for w in re.split(r"[^a-z0-9]+", title.lower()) if w and w not in stop]
    return " ".join(words)[:120] or None


def cross_source_basis(a, b) -> str | None:
    """basis сильной связи или None. Слабая определяется отдельно."""
    key_a, key_b = normalize_url_key(a.apply_url or a.source_url), \
        normalize_url_key(b.apply_url or b.source_url)
    if key_a and key_a == key_b:
        return "strong:same_apply_url"
    id_a = getattr(a, "requisition_id", None)
    id_b = getattr(b, "requisition_id", None)
    if id_a and id_a == id_b:
        return "strong:same_requisition_id"
    return None


def cross_source_candidate(a, b) -> str | None:
    """Слабый кандидат на дубль между площадками (без слияния)."""
    if a.source == b.source:
        return None
    if company_slug(a.company_name) != company_slug(b.company_name):
        return None
    if title_slug(a.title) != title_slug(b.title):
        return None
    if (a.city or "").lower() != (b.city or "").lower():
        return None
    return "weak:company_title_city"
