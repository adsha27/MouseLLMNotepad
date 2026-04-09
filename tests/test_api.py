from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

import httpx
import pytest

from mousekb.api import create_app
from mousekb.config import CLIENT_SECRET_HEADER, Settings


@asynccontextmanager
async def build_client(tmp_path):
    settings = Settings.from_root(tmp_path)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, settings


def auth_headers(settings: Settings) -> dict[str, str]:
    return {CLIENT_SECRET_HEADER: settings.ensure_client_secret()}


@pytest.mark.anyio
async def test_public_browser_capture_writes_snapshot_and_search_index(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        response = await client.post(
            "/captures/browser",
            headers=auth_headers(settings),
            json={
                "selected_text": "Persistent wiki systems keep compounding notes close to the original evidence.",
                "page_url": "https://example.com/persistent-wiki",
                "page_title": "Persistent Wiki Notes",
                "page_snapshot_markdown": "## Why this matters\n\nBecause raw sources should stay queryable.",
                "is_public_source": True,
                "user_note": "Feels close to the MouseKB direction.",
                "tags": ["knowledge-base", "persistent-wiki"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["snapshot_path"]
        assert (settings.project_root / payload["raw_path"]).exists()
        assert (settings.project_root / payload["snapshot_path"]).exists()
        assert (settings.project_root / payload["inbox_path"]).exists()

        search = await client.get("/search", params={"q": "persistent wiki evidence"}, headers=auth_headers(settings))
        assert search.status_code == 200
        results = search.json()
        assert results["total"] >= 1
        assert results["items"][0]["id"] == payload["id"]


@pytest.mark.anyio
async def test_private_capture_skips_snapshot_and_secret_is_required(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        unauthorized = await client.post(
            "/captures/clipboard",
            json={"copied_text": "This should fail without the secret."},
        )
        assert unauthorized.status_code == 401

        response = await client.post(
            "/captures/browser",
            headers=auth_headers(settings),
            json={
                "selected_text": "Private chat snippet with personal context.",
                "page_url": "https://chat.example.internal/thread/123",
                "page_title": "Private thread",
                "page_snapshot_markdown": "# full page that should not be kept by default",
                "is_public_source": False,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["snapshot_path"] is None
        assert payload["sensitivity"] == "private"


@pytest.mark.anyio
async def test_profile_review_and_context_pack_include_opposition_and_raw_notes(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        headers = auth_headers(settings)

        first = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "I want first principles, evidence, citations, and proofs when evaluating mechanistic interpretability claims.",
                "page_url": "https://example.com/mi-principles",
                "page_title": "Mechanistic interpretability from first principles",
                "page_snapshot_markdown": "## Claims\n\nStrong evidence and source discipline matter.",
                "is_public_source": True,
                "tags": ["mechanistic interpretability"],
            },
        )
        assert first.status_code == 200

        second = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "Counterargument: the anti-case against mechanistic interpretability says the evidence is still thin and objections matter.",
                "page_url": "https://example.com/mi-counterargument",
                "page_title": "The anti-case",
                "page_snapshot_markdown": "## Objections\n\nThere are still open objections.",
                "is_public_source": True,
                "tags": ["mechanistic interpretability"],
            },
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["contrarian"] is True

        profile = await client.get("/profile", headers=headers)
        assert profile.status_code == 200
        profile_payload = profile.json()
        assert profile_payload["pending"]

        suggestion_id = profile_payload["pending"][0]["id"]
        approve = await client.post(f"/profile-suggestions/{suggestion_id}/approve", headers=headers)
        assert approve.status_code == 200
        approved_payload = approve.json()
        assert approved_payload["approved"]

        context_pack = await client.post(
            "/context-packs",
            headers=headers,
            json={
                "query": "mechanistic interpretability evidence objections",
                "include_raw_note_ids": [second_payload["id"]],
                "max_items": 6,
                "mode": "balanced",
            },
        )
        assert context_pack.status_code == 200
        pack_payload = context_pack.json()
        assert pack_payload["opposing_notes"]
        assert "Explicit Raw Notes" in pack_payload["export_text"]
        assert second_payload["id"] in pack_payload["export_text"]


@pytest.mark.anyio
async def test_reindex_restores_captures_from_markdown(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        headers = auth_headers(settings)

        response = await client.post(
            "/captures/clipboard",
            headers=headers,
            json={
                "copied_text": "Proofs and empirical evidence should stay attached to arguments.",
                "source_app": "terminal",
            },
        )
        assert response.status_code == 200

        connection = sqlite3.connect(settings.db_path)
        connection.execute("DELETE FROM captures")
        connection.execute("DELETE FROM captures_fts")
        connection.commit()
        connection.close()

        search_before = await client.get("/search", params={"q": "empirical evidence"}, headers=headers)
        assert search_before.status_code == 200
        assert search_before.json()["total"] == 0

        reindex = await client.post("/admin/reindex", headers=headers)
        assert reindex.status_code == 200
        assert reindex.json()["reindexed_captures"] == 1

        search_after = await client.get("/search", params={"q": "empirical evidence"}, headers=headers)
        assert search_after.status_code == 200
        assert search_after.json()["total"] == 1
