"""Version read responses without bypassing any authentication dependencies."""
from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from bff.read_cache import data_version
from bff.registry import connected_adapters

_READ_PATH = re.compile(
    r"/api/v1/(?:brands(?:/[^/]+(?:/(?:overview|menu|products|promotions|changes)"
    r"(?:/[^/]+(?:/history)?)?)?)?|market/(?:overview|changes|promotions)|changes/[^/]+)"
)


def current_version() -> str | None:
    return data_version(connected_adapters())


class VersionedReadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def read(request: Request):
            if request.method != "GET" or not _READ_PATH.fullmatch(request.url.path):
                return await handler(request)
            before = current_version()
            # Always run dependencies, including authentication, even for repeats.
            response = await handler(request)
            if response.status_code == 200:
                after = current_version()
                if before is not None and after is not None and before != after:
                    # Never label an old/inconsistent result with a newer version.
                    return JSONResponse(
                        {"detail": {"error": "data_changed_during_read"}},
                        status_code=409, headers={"Cache-Control": "no-store"},
                    )
                if before is not None and before == after:
                    response.headers["X-Data-Version"] = before
                response.headers["Cache-Control"] = "no-store"
            return response

        return read
