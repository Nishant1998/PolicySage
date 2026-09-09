from fastapi import HTTPException


def upload_path(path):
    prefix = "/api/admin/kb/documents"
    return path == prefix or (path.startswith(prefix + "/") and path.endswith("/revisions"))


def body_limit(path):
    # Includes JSON escaping overhead for the bounded four-turn conversation.
    return 21 * 1024 * 1024 if upload_path(path) else 384 * 1024


class RequestBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or not (
            scope["path"] == "/api/chat" or upload_path(scope["path"])
        ):
            return await self.app(scope, receive, send)
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > body_limit(scope["path"]):
                    raise HTTPException(413, "Request is too large.")
            return message

        await self.app(scope, limited_receive, send)
