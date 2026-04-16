from __future__ import annotations

import math
import sqlite3
from contextlib import asynccontextmanager

import httpx
import pytest

from mousekb import embeddings as embedding_module
from mousekb.api import create_app
from mousekb.config import CLIENT_SECRET_HEADER, Settings


def _normalized(values: list[float]) -> list[float] | None:
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        return None
    return [value / norm for value in values]


def _fake_embedding(text: str) -> list[float] | None:
    lowered = text.lower()
    vector = [0.0, 0.0, 0.0, 0.0]

    if any(token in lowered for token in ("fast capture", "instant", "immediately", "indexing", "background organization")):
        vector[0] += 1.0
    if any(token in lowered for token in ("proof", "proofs", "evidence", "citation", "citations", "source-backed")):
        vector[1] += 1.0
    if any(token in lowered for token in ("mechanistic interpretability", "model circuits", "counterargument", "skeptical", "objection", "anti-case")):
        vector[2] += 1.0
    if any(token in lowered for token in ("privacy", "local-first", "private", "sensitive")):
        vector[3] += 1.0

    return _normalized(vector)


@pytest.fixture(autouse=True)
def stub_local_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_module.LocalEmbeddingEngine, "embed_text", lambda self, text: _fake_embedding(text))


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
        assert payload["stance"] == "neutral"
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
async def test_hybrid_search_prefers_exact_match_and_supports_semantic_recall(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        headers = auth_headers(settings)

        exact = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "Mechanistic interpretability needs evidence, objections, and careful proofs.",
                "page_url": "https://example.com/mech-interp",
                "page_title": "Mechanistic interpretability evidence objections",
                "page_snapshot_markdown": "## Notes\n\nObjections matter.",
                "is_public_source": True,
                "tags": ["mechanistic interpretability", "proofs"],
            },
        )
        assert exact.status_code == 200
        exact_id = exact.json()["id"]

        semantic = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "A good system should save instantly and let background organization happen later.",
                "page_url": "https://example.com/fast-capture",
                "page_title": "Fast capture without blocking",
                "page_snapshot_markdown": "## Notes\n\nCapture should return immediately.",
                "is_public_source": True,
                "tags": ["fast capture"],
            },
        )
        assert semantic.status_code == 200
        semantic_id = semantic.json()["id"]

        process = await client.post("/admin/process-pending", headers=headers)
        assert process.status_code == 200

        exact_search = await client.get(
            "/search",
            params={"q": "mechanistic interpretability evidence objections"},
            headers=headers,
        )
        assert exact_search.status_code == 200
        exact_payload = exact_search.json()
        assert exact_payload["items"][0]["id"] == exact_id
        assert "matched exact terms" in exact_payload["items"][0]["reasons"]

        semantic_search = await client.get(
            "/search",
            params={"q": "saving selections instantly while indexing happens later"},
            headers=headers,
        )
        assert semantic_search.status_code == 200
        semantic_payload = semantic_search.json()
        assert semantic_payload["items"][0]["id"] == semantic_id
        assert "semantic overlap" in semantic_payload["items"][0]["reasons"]


@pytest.mark.anyio
async def test_stance_override_topic_cards_and_ai_context_pack(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        headers = auth_headers(settings)

        support_capture = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "Fast capture should stay local-first and keep evidence close to the saved note.",
                "page_url": "https://example.com/fast-capture-support",
                "page_title": "Fast capture support",
                "page_snapshot_markdown": "## Notes\n\nEvidence trails matter.",
                "is_public_source": True,
                "tags": ["fast capture", "proofs"],
            },
        )
        assert support_capture.status_code == 200
        support_id = support_capture.json()["id"]

        opposing_capture = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "Counterargument: fast capture tools become bloated when privacy boundaries are fuzzy and objections get buried.",
                "page_url": "https://example.com/fast-capture-risk",
                "page_title": "Fast capture anti-case",
                "page_snapshot_markdown": "## Risks\n\nCounterarguments prevent self-propaganda.",
                "is_public_source": True,
                "tags": ["fast capture", "privacy"],
            },
        )
        assert opposing_capture.status_code == 200
        opposing_id = opposing_capture.json()["id"]
        assert opposing_capture.json()["stance"] == "opposing"

        review = await client.post(
            f"/captures/{support_id}/review",
            headers=headers,
            json={
                "review_note": "Keep this as the main supporting case for the fast-capture architecture.",
                "review_tags": ["fast capture", "proofs"],
                "stance_override": "supporting",
            },
        )
        assert review.status_code == 200
        assert review.json()["stance"] == "supporting"

        process = await client.post("/admin/process-pending", headers=headers)
        assert process.status_code == 200

        search = await client.get("/search", params={"q": "fast capture privacy evidence"}, headers=headers)
        assert search.status_code == 200
        result_stances = {item["id"]: item["stance"] for item in search.json()["items"]}
        assert result_stances[support_id] == "supporting"
        assert result_stances[opposing_id] == "opposing"

        topic_cards = await client.get("/ai/topic-cards", params={"q": "fast capture"}, headers=headers)
        assert topic_cards.status_code == 200
        topic_payload = topic_cards.json()
        assert topic_payload["total"] >= 1
        first_card = topic_payload["items"][0]
        assert first_card["support_count"] >= 1
        assert first_card["oppose_count"] >= 1

        ai_pack = await client.post(
            "/ai/context-packs",
            headers=headers,
            json={
                "query": "fast capture privacy evidence",
                "max_items": 6,
                "mode": "balanced",
            },
        )
        assert ai_pack.status_code == 200
        pack_payload = ai_pack.json()
        assert "Counterarguments or cautionary notes:" in pack_payload["share_text"]
        assert "Fast capture anti-case" in pack_payload["share_text"]
        assert "No explicit opposing evidence" not in pack_payload["share_text"]


@pytest.mark.anyio
async def test_ai_context_pack_calls_out_missing_opposition(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        headers = auth_headers(settings)

        response = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "Evidence-backed local-first notes help frontier chats feel continuous.",
                "page_url": "https://example.com/local-first",
                "page_title": "Local-first continuity",
                "page_snapshot_markdown": "## Notes\n\nKeep raw captures local.",
                "is_public_source": True,
                "tags": ["local-first", "proofs"],
            },
        )
        assert response.status_code == 200

        process = await client.post("/admin/process-pending", headers=headers)
        assert process.status_code == 200

        ai_pack = await client.post(
            "/ai/context-packs",
            headers=headers,
            json={"query": "local-first continuity", "max_items": 4, "mode": "balanced"},
        )
        assert ai_pack.status_code == 200
        assert "No explicit opposing evidence was found for this topic in MouseKB yet." in ai_pack.json()["share_text"]


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


@pytest.mark.anyio
async def test_search_falls_back_to_lexical_when_embeddings_are_unavailable(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(embedding_module.LocalEmbeddingEngine, "embed_text", lambda self, text: None)

    async with build_client(tmp_path) as (client, settings):
        headers = auth_headers(settings)
        response = await client.post(
            "/captures/browser",
            headers=headers,
            json={
                "selected_text": "Lexical retrieval should still work when embeddings are not available.",
                "page_url": "https://example.com/lexical-only",
                "page_title": "Lexical fallback",
                "page_snapshot_markdown": "## Notes\n\nDense recall is optional.",
                "is_public_source": True,
                "tags": ["retrieval"],
            },
        )
        assert response.status_code == 200

        search = await client.get("/search", params={"q": "lexical retrieval"}, headers=headers)
        assert search.status_code == 200
        assert search.json()["total"] == 1
        assert search.json()["items"][0]["title"] == "Lexical fallback"


@pytest.mark.anyio
async def test_chat_wrapup_saves_structured_note_and_legacy_context_route_is_removed(tmp_path):
    async with build_client(tmp_path) as (client, settings):
        headers = auth_headers(settings)

        legacy = await client.post(
            "/context-packs",
            headers=headers,
            json={"query": "should fail"},
        )
        assert legacy.status_code == 404

        wrapup = await client.post(
            "/ai/chat-wrapups",
            headers=headers,
            json={
                "source_app": "chatgpt",
                "source_url": "https://chatgpt.com/c/example",
                "conversation_title": "MouseLLM architecture",
                "user_note": "Save only the durable pieces.",
                "messages": [
                    {"role": "user", "content": "We need fast capture, delayed review, and lightweight post-processing."},
                    {"role": "assistant", "content": "The KB should include counterarguments so it does not become self-propaganda."},
                    {"role": "user", "content": "Open question: how do we explain the plain ChatGPT paste flow clearly?"},
                ],
            },
        )
        assert wrapup.status_code == 200
        wrapup_payload = wrapup.json()
        assert wrapup_payload["source_app"] == "chatgpt"
        assert wrapup_payload["summary"]
        assert wrapup_payload["capture_id"]
        assert (settings.project_root / wrapup_payload["inbox_path"]).exists()
