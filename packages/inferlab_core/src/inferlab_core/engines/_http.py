"""Shared local HTTP transport policy and strict JSON primitives."""

import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Self

import httpx

from .errors import (
    EngineConnectionError,
    EngineHTTPError,
    EngineRemoteError,
    EngineResponseError,
    EngineTimeoutError,
    ModelNotFoundError,
)


@contextmanager
def transport_errors() -> Iterator[None]:
    try:
        yield
    except httpx.TimeoutException:
        raise EngineTimeoutError("Engine request timed out") from None
    except httpx.RequestError:
        raise EngineConnectionError("Engine transport failed") from None


def json_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise EngineResponseError("Expected a JSON object")
    result: dict[str, object] = dict(value)
    if "error" in result:
        raise EngineRemoteError("Engine reported an error")
    return result


def parse_json(value: str | bytes) -> dict[str, object]:
    try:
        return json_object(json.loads(value))
    except (ValueError, UnicodeError):
        raise EngineResponseError("Invalid engine JSON") from None


def string_field(data: dict[str, object], key: str, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise EngineResponseError(f"Invalid string field: {key}")
    return value


def optional_string(data: dict[str, object], key: str) -> str | None:
    return None if data.get(key) is None else string_field(data, key)


def count_field(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise EngineResponseError(f"Invalid nonnegative integer field: {key}")
    return value


class LocalHTTPTransport:
    """Loopback only; no redirects/retries/proxies for owned clients or shell I/O."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        url = httpx.URL(base_url)
        if (
            url.scheme not in {"http", "https"}
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.userinfo
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("Engine base_url must be a loopback origin without credentials")
        self._base_url = str(url).rstrip("/")
        self._timeout = timeout or httpx.Timeout(connect=5, read=60, write=10, pool=5)
        for duration in self._timeout.as_dict().values():
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise ValueError("All HTTP timeouts must be finite and positive")
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(trust_env=False)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _status(response: httpx.Response, *, model_request: bool = False) -> None:
        if model_request and response.status_code == 404:
            raise ModelNotFoundError(404)
        if not response.is_success:
            raise EngineHTTPError(response.status_code)

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        model_request: bool = False,
    ) -> dict[str, object]:
        with transport_errors():
            response = await self._client.request(
                method,
                self._base_url + path,
                json=payload,
                timeout=self._timeout,
                follow_redirects=False,
            )
            self._status(response, model_request=model_request)
            return parse_json(response.content)
