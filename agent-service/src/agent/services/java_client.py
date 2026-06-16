"""Shared HTTP client for Java backend internal APIs.

Provides a singleton httpx.Client with unified auth header, base URL,
and timeout. All @tool functions that call the Java backend should
use get_java_client() instead of creating their own httpx.Client.
"""

import logging
import os

import httpx

logger = logging.getLogger("pick.services.java_client")

# Config
JAVA_BASE_URL = os.environ.get("JAVA_BASE_URL", "http://localhost:8085")
INTERNAL_TOKEN = os.environ.get("SYNC_INTERNAL_TOKEN", "internal-dev-token")
REQUEST_TIMEOUT = 15.0  # seconds (accommodates slowest endpoint)


def get_java_client(timeout: float | None = None) -> httpx.Client:
    """Return a configured httpx.Client for Java internal API calls.

    The client is created on each call (httpx.Client is not thread-safe).
    Callers should use it as a context manager:

        with get_java_client() as client:
            response = client.get("/api/...")

    Args:
        timeout: Override default timeout in seconds. If None, uses
                 REQUEST_TIMEOUT (15.0).
    """
    return httpx.Client(
        base_url=JAVA_BASE_URL,
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        timeout=timeout or REQUEST_TIMEOUT,
    )
