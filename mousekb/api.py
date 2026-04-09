from __future__ import annotations

import hmac
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from .config import CLIENT_SECRET_HEADER, Settings, get_settings
from .models import (
    BrowserCaptureIn,
    CaptureRecord,
    ClipboardCaptureIn,
    ContextPackRequest,
    ContextPackResponse,
    HealthResponse,
    ProfileResponse,
    SearchResponse,
)
from .store import MouseKBStore


ALLOWED_ORIGIN_PREFIXES = (
    "http://127.0.0.1",
    "http://localhost",
    "chrome-extension://",
    "moz-extension://",
)

def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    store_box: dict[str, MouseKBStore] = {}

    def current_store() -> MouseKBStore:
        if "store" not in store_box:
            store_box["store"] = MouseKBStore(resolved_settings)
        return store_box["store"]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        store = store_box.pop("store", None)
        if store is not None:
            store.close()

    app = FastAPI(title="MouseKB", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def guard_local_requests(request: Request, call_next: Callable[[Request], Any]) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin and not origin.startswith(ALLOWED_ORIGIN_PREFIXES):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Origin not allowed"},
            )

        if request.method == "OPTIONS":
            if not origin:
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": "Origin required"})
            return _cors_response(origin)

        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1", None}:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Loopback requests only"},
            )

        expected_secret = current_store().secret
        provided_secret = request.headers.get(CLIENT_SECRET_HEADER)
        if not provided_secret or not hmac.compare_digest(provided_secret, expected_secret):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid client secret"},
                headers=_cors_headers(origin),
            )

        response = await call_next(request)
        _apply_cors_headers(response, origin)
        return response

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", bind=f"{resolved_settings.bind_host}:{resolved_settings.bind_port}")

    @app.post("/captures/browser", response_model=CaptureRecord)
    async def create_browser_capture(payload: BrowserCaptureIn) -> CaptureRecord:
        try:
            record = current_store().save_browser_capture(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return CaptureRecord.model_validate(record)

    @app.post("/captures/clipboard", response_model=CaptureRecord)
    async def create_clipboard_capture(payload: ClipboardCaptureIn) -> CaptureRecord:
        try:
            record = current_store().save_clipboard_capture(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return CaptureRecord.model_validate(record)

    @app.get("/search", response_model=SearchResponse)
    async def search(q: str) -> SearchResponse:
        items = current_store().search(q)
        return SearchResponse(query=q, total=len(items), items=items)

    @app.post("/context-packs", response_model=ContextPackResponse)
    async def build_context_pack(payload: ContextPackRequest) -> ContextPackResponse:
        result = current_store().build_context_pack(
            query=payload.query,
            include_raw_note_ids=payload.include_raw_note_ids,
            max_items=payload.max_items,
            mode=payload.mode,
        )
        return ContextPackResponse.model_validate(result)

    @app.get("/profile", response_model=ProfileResponse)
    async def get_profile() -> ProfileResponse:
        return ProfileResponse.model_validate(current_store().get_profile())

    @app.post("/profile-suggestions/{suggestion_id}/approve", response_model=ProfileResponse)
    async def approve_profile_suggestion(suggestion_id: str) -> ProfileResponse:
        try:
            profile = current_store().approve_profile_suggestion(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found") from exc
        return ProfileResponse.model_validate(profile)

    @app.post("/profile-suggestions/{suggestion_id}/reject", response_model=ProfileResponse)
    async def reject_profile_suggestion(suggestion_id: str) -> ProfileResponse:
        try:
            profile = current_store().reject_profile_suggestion(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found") from exc
        return ProfileResponse.model_validate(profile)

    @app.post("/admin/reindex")
    async def reindex() -> dict[str, int]:
        return current_store().reindex_from_markdown()

    return app


def _cors_headers(origin: str | None) -> dict[str, str]:
    if not origin or not origin.startswith(ALLOWED_ORIGIN_PREFIXES):
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": f"content-type,{CLIENT_SECRET_HEADER}",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Vary": "Origin",
    }


def _apply_cors_headers(response: Response, origin: str | None) -> None:
    for key, value in _cors_headers(origin).items():
        response.headers[key] = value


def _cors_response(origin: str) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _apply_cors_headers(response, origin)
    return response


app = create_app()
