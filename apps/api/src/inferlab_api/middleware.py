"""Bound request bodies before parsing and attach server-generated request IDs."""

import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 65536


class RequestBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = secrets.token_hex(16)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower()
                    not in {b"x-request-id", b"cache-control", b"x-content-type-options"}
                ]
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        async def reject(status: int, code: str, message: str) -> None:
            response = JSONResponse(
                status_code=status,
                content={"error": {"code": code, "message": message, "request_id": request_id}},
            )
            await response(scope, receive, send_headers)

        headers = dict(scope["headers"])
        if headers.get(b"content-encoding", b"identity") != b"identity":
            await reject(415, "unsupported_encoding", "Compressed request bodies are not accepted.")
            return
        length = headers.get(b"content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                declared = -1
            if declared < 0:
                await reject(400, "invalid_length", "Invalid Content-Length.")
                return
            if declared > MAX_BODY_BYTES:
                await reject(413, "body_too_large", "Request body exceeds 64 KiB.")
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                await reject(413, "body_too_large", "Request body exceeds 64 KiB.")
                return
            if not message.get("more_body", False):
                break
        consumed = False

        async def bounded_receive() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send_headers)
