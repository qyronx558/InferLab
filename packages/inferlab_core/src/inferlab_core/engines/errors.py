"""Transport errors deliberately omit prompts, response bodies and local paths."""


class EngineError(Exception):
    """Base class for engine failures; task cancellation is never wrapped."""


class EngineTimeoutError(EngineError):
    """A connect, read, write or pool timeout expired."""


class EngineConnectionError(EngineError):
    """The HTTP transport failed (including interrupted response bodies)."""


class EngineHTTPError(EngineError):
    """The server returned an unsuccessful HTTP status."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Engine HTTP status {status_code}")


class ModelNotFoundError(EngineHTTPError):
    """The requested model is unavailable; no download is attempted."""


class EngineResponseError(EngineError):
    """The response is malformed, incomplete, or violates the wire contract."""


class EngineRemoteError(EngineError):
    """An engine error object was received, possibly after streaming began."""
