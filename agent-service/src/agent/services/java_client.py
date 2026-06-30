"""Shared HTTP client for Java backend internal APIs.

Provides a singleton httpx.Client with connection pooling, unified auth
header, exponential-backoff retry, and a simple circuit breaker.

All @tool functions that call the Java backend should use
get_java_client() instead of creating their own httpx.Client.
"""

import logging
import os
import time
import threading
from typing import Callable

import httpx

logger = logging.getLogger("pick.services.java_client")

# ── Config ──────────────────────────────────────────────────────────────

JAVA_BASE_URL = os.environ.get("JAVA_BASE_URL", "http://localhost:8085")
INTERNAL_TOKEN = os.environ.get("SYNC_INTERNAL_TOKEN", "internal-dev-token")

REQUEST_TIMEOUT = float(os.environ.get("JAVA_REQUEST_TIMEOUT", "15.0"))
MAX_RETRIES = int(os.environ.get("JAVA_MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = float(os.environ.get("JAVA_RETRY_BACKOFF", "0.5"))
CIRCUIT_BREAKER_THRESHOLD = int(os.environ.get("JAVA_CB_THRESHOLD", "5"))
CIRCUIT_BREAKER_COOLDOWN = float(os.environ.get("JAVA_CB_COOLDOWN", "30.0"))

# ── Connection pool singleton ──────────────────────────────────────────

_client: httpx.Client | None = None
_client_lock = threading.Lock()


# ── Circuit breaker state ──────────────────────────────────────────────

_failure_count = 0
_last_failure_time = 0.0
_cb_lock = threading.Lock()


def _circuit_open() -> bool:
    """Return True if the circuit breaker is currently open (failing fast)."""
    with _cb_lock:
        if _failure_count >= CIRCUIT_BREAKER_THRESHOLD:
            if time.monotonic() - _last_failure_time < CIRCUIT_BREAKER_COOLDOWN:
                return True
            # Cooldown elapsed → half-open
            _failure_count = 0
    return False


def _record_success() -> None:
    with _cb_lock:
        _failure_count = 0


def _record_failure() -> None:
    with _cb_lock:
        _failure_count += 1
        _last_failure_time = time.monotonic()


# ── Public API ──────────────────────────────────────────────────────────


def get_java_client(timeout: float | None = None) -> httpx.Client:
    """Return a shared httpx.Client with connection pooling.

    The client is created once and reused across calls.  httpx.Client is
    thread-safe for synchronous use as long as it is not modified after
    creation.

    Usage::

        client = get_java_client()
        response = client.get("/api/...")
        response.raise_for_status()

    Args:
        timeout: Override default timeout in seconds.  If None, uses
                 REQUEST_TIMEOUT (default 15.0).

    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-check
                _client = httpx.Client(
                    base_url=JAVA_BASE_URL,
                    headers={"X-Internal-Token": INTERNAL_TOKEN},
                    timeout=timeout or REQUEST_TIMEOUT,
                    limits=httpx.Limits(
                        max_keepalive_connections=10,
                        max_connections=20,
                    ),
                )
                logger.info(
                    "Java client pool created: base=%s timeout=%.1fs",
                    JAVA_BASE_URL,
                    timeout or REQUEST_TIMEOUT,
                )
    return _client


def retry_on_server_error(
    max_retries: int | None = None,
    backoff_base: float | None = None,
) -> Callable:
    """Decorator: retry a function on 5xx / network errors with exponential backoff.

    Usage::

        @retry_on_server_error()
        def call_java_api(...):
            ...
    """
    _max = max_retries if max_retries is not None else MAX_RETRIES
    _base = backoff_base if backoff_base is not None else RETRY_BACKOFF_BASE

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(_max + 1):
                if _circuit_open():
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker open — {CIRCUIT_BREAKER_COOLDOWN}s cooldown"
                    )
                try:
                    result = func(*args, **kwargs)
                    _record_success()
                    return result
                except httpx.HTTPStatusError as exc:
                    if 400 <= exc.response.status_code < 500:
                        # Client errors (4xx) — don't retry
                        _record_failure()
                        raise
                    # Server errors (5xx) — retry
                    last_exc = exc
                    if attempt < _max:
                        delay = _base * (2 ** attempt)
                        logger.warning(
                            "Java API retry %d/%d after %.1fs (HTTP %d)",
                            attempt + 1, _max, delay,
                            exc.response.status_code,
                        )
                        time.sleep(delay)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                    last_exc = exc
                    if attempt < _max:
                        delay = _base * (2 ** attempt)
                        logger.warning(
                            "Java API retry %d/%d after %.1fs (%s)",
                            attempt + 1, _max, delay, type(exc).__name__,
                        )
                        time.sleep(delay)
            # All retries exhausted
            _record_failure()
            raise RuntimeError(
                f"Java API call failed after {_max} retries"
            ) from last_exc
        return wrapper
    return decorator


class CircuitBreakerOpenError(RuntimeError):
    """Raised when the circuit breaker is open — failing fast."""
    pass


def close_java_client() -> None:
    """Explicitly close the shared client (for graceful shutdown)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("Java client pool closed")
