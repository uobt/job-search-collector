"""Контракт коннектора источника."""

from __future__ import annotations

from ..models import SearchSpec, SearchPage


class SourceBlocked(RuntimeError):
    """Прямой сбор запрещён политикой (robots/ToS) — не техническая ошибка."""

    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: прямой сбор заблокирован политикой: {reason}")
        self.source = source
        self.reason = reason


class Connector:
    code: str = ""
    label: str = ""
    live_allowed: bool = True
    policy_reason: str | None = None
    page_step: int = 10

    def build_search_url(self, spec: SearchSpec, query: str, location,
                         cursor: str | None) -> str:
        raise NotImplementedError

    def parse_search(self, html: str) -> SearchPage:
        """Чистый парсер: только сохранённый HTML, без сети."""
        raise NotImplementedError

    def parse_detail(self, html: str):
        """Чистый парсер карточки; None → источник не отдаёт карточки в выдаче."""
        return None
