"""Bound chat bodies while receiving them, including chunked requests."""

from fastapi.responses import JSONResponse

MAX_CHAT_BODY_BYTES = 16384
MAX_LOGIN_BODY_BYTES = 1024


class ChatBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["path"] not in {"/api/chat", "/api/access/login"}
            or scope["method"] != "POST"
        ):
            return await self.app(scope, receive, send)
        limit = MAX_CHAT_BODY_BYTES if scope["path"] == "/api/chat" else MAX_LOGIN_BODY_BYTES
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await JSONResponse(
                    status_code=413, content={"detail": "Request body is too large."}
                )(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)
