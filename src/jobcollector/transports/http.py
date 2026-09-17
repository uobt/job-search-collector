"""HTTP-транспорт: троттлинг на хост, ретраи на временные ошибки, Retry-After,
SSRF-защита (редиректы и private-сети), бюджет запросов. Stdlib only."""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field

from ..models import RawDocument, utcnow

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


class TransportError(RuntimeError):
    def __init__(self, message: str, status: int | None = None,
                 blocked: bool = False):
        super().__init__(message)
        self.status = status
        self.blocked = blocked  # 403/captcha-подобные отказы не ретраятся


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def _is_private_host(hostname: str) -> bool:
    """Не ходим на localhost/link-local/private диапазоны из внешних данных."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return False  # DNS не разрешился — urllib сам выдаст ошибку
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not addr.is_global:
            return True
    return False


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Редирект разрешаем только на публичные хосты (SSRF-guard)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = _host(newurl)
        if not host or _is_private_host(host):
            raise TransportError(f"редирект на приватный/недопустимый хост: {newurl}",
                                 status=code, blocked=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class _Budget:
    max_requests: int
    used: int = 0

    def take(self) -> bool:
        if self.used >= self.max_requests:
            return False
        self.used += 1
        return True


@dataclass
class HttpTransport:
    delay_seconds: float = 2.0
    timeout: float = 30.0
    max_retries: int = 2
    max_requests: int = 200
    user_agent: str = USER_AGENT
    _last_hit: dict[str, float] = field(default_factory=dict, repr=False)
    _budget: _Budget | None = None

    def __post_init__(self) -> None:
        self._budget = _Budget(self.max_requests)

    # --- публичное ---

    def get(self, url: str, extra_headers: dict[str, str] | None = None,
            allow_private: bool = False) -> RawDocument:
        host = _host(url)
        if not allow_private and _is_private_host(host):
            raise TransportError(f"запрос к приватному хосту запрещён: {host}", blocked=True)
        if not self._budget.take():
            raise TransportError("исчерпан бюджет запросов прогона")

        last_error: TransportError | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle(host)
            request = urllib.request.Request(url, method="GET")
            request.add_header("User-Agent", self.user_agent)
            request.add_header("Accept", "text/html,application/xhtml+xml,"
                                         "application/json;q=0.9,*/*;q=0.5")
            request.add_header("Accept-Language", "en-GB,en;q=0.9")
            for name, value in (extra_headers or {}).items():
                request.add_header(name, value)
            try:
                opener = urllib.request.build_opener(SafeRedirectHandler())
                with opener.open(request, timeout=self.timeout) as response:
                    body = response.read().decode(
                        response.headers.get_content_charset() or "utf-8",
                        errors="replace")
                    return RawDocument(
                        request_id=uuid.uuid4().hex[:12],
                        url=url, fetched_at=utcnow(),
                        status=response.status,
                        mime=response.headers.get_content_type(),
                        content=body)
            except urllib.error.HTTPError as exc:
                # тело читаем для raw, но наверх — ошибка с кодом
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                blocked_like = exc.code in (401, 403) or exc.code == 200 and False
                err = TransportError(f"HTTP {exc.code} на {url}", status=exc.code,
                                     blocked=blocked_like or exc.code in (401, 403))
                err.raw = RawDocument(request_id=uuid.uuid4().hex[:12], url=url,
                                      fetched_at=utcnow(), status=exc.code,
                                      mime=None, content=body)
                if exc.code not in RETRYABLE:
                    raise err
                self._respect_retry_after(exc.headers.get("Retry-After"))
                last_error = err
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = TransportError(f"{type(exc).__name__}: {exc} на {url}")
        raise last_error or TransportError(f"не удалось получить {url}")

    # --- внутреннее ---

    def _throttle(self, host: str) -> None:
        now = time.monotonic()
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.delay_seconds - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def _respect_retry_after(self, value: str | None) -> None:
        """Retry-After: секунды ИЛИ HTTP-date. Не сокращаем серверную задержку;
        сверх лимита — мгновенный повторный отказ наверх (задача отложится)."""
        if not value:
            time.sleep(min(30.0, self.delay_seconds * 2))
            return
        try:
            delay = float(value)
        except ValueError:
            from email.utils import parsedate_to_datetime
            try:
                target = parsedate_to_datetime(value)
                delay = (target - __import__("datetime")
                         .datetime.now(__import__("datetime").timezone.utc)).total_seconds()
            except Exception:
                delay = self.delay_seconds * 2
        if 0 < delay <= 120:
            time.sleep(delay + 0.5)
