from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .embeddings import LocalEmbeddingEngine
from .heuristics import (
    classify_sensitivity,
    cosine_similarity,
    detect_reasoning_cues,
    extract_keyphrases,
    infer_stance,
    normalize_text,
    snippet_for_query,
)
from .markdown_utils import (
    build_capture_markdown,
    build_snapshot_markdown,
    parse_capture_markdown,
    relative_path,
    slugify,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class MouseKBStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_layout()
        self.settings.ensure_client_secret()
        self._lock = threading.RLock()
        self._worker_state_lock = threading.Lock()
        self._worker_running = False
        self._connection = sqlite3.connect(self.settings.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._embeddings = LocalEmbeddingEngine(self.settings.embedding_cache_dir)
        self._init_db()
        self._write_profile_markdown()
        self._rebuild_profile_weights_locked()
        self._rebuild_share_policies_locked()

    @property
    def secret(self) -> str:
        return self.settings.ensure_client_secret()

    def close(self) -> None:
        self._connection.close()

    def save_browser_capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = (payload.get("selected_text") or "").strip()
        if not text:
            raise ValueError("selected_text is required")

        created_at = utc_now()
        capture_id = f"cap_{uuid.uuid4().hex[:12]}"
        page_title = (payload.get("page_title") or "Untitled Page").strip()
        page_url = (payload.get("page_url") or "").strip() or None
        user_note = (payload.get("user_note") or "").strip() or None
        tags = self._dedupe_terms(payload.get("tags") or [])
        sensitivity = classify_sensitivity(
            source_type="browser",
            page_url=page_url,
            is_public_source=bool(payload.get("is_public_source")),
        )
        is_public_source = bool(payload.get("is_public_source")) and sensitivity == "public"
        snapshot_markdown = payload.get("page_snapshot_markdown") or None
        stance = infer_stance(" ".join(filter(None, [page_title, text, user_note or ""])))

        with self._lock:
            raw_path = self._write_raw_capture(
                capture_id=capture_id,
                created_at=created_at,
                source_type="browser",
                selected_text=text,
                user_note=user_note,
                metadata={
                    "id": capture_id,
                    "created_at": created_at.isoformat(),
                    "source_type": "browser",
                    "page_url": page_url,
                    "page_title": page_title,
                    "source_app": None,
                    "is_public_source": is_public_source,
                    "sensitivity": sensitivity,
                    "tags_json": tags,
                    "stance": stance,
                },
                slug_seed=page_title or capture_id,
            )
            snapshot_path = None
            if snapshot_markdown and is_public_source:
                snapshot_path = self._write_snapshot(
                    capture_id=capture_id,
                    created_at=created_at,
                    page_title=page_title,
                    page_url=page_url or "",
                    markdown=snapshot_markdown,
                )

            record = self._build_hot_capture_record(
                capture_id=capture_id,
                source_type="browser",
                created_at=created_at.isoformat(),
                selected_text=text,
                page_url=page_url,
                page_title=page_title,
                source_app=None,
                user_note=user_note,
                is_public_source=is_public_source,
                sensitivity=sensitivity,
                raw_path=relative_path(raw_path, self.settings.project_root),
                snapshot_path=relative_path(snapshot_path, self.settings.project_root) if snapshot_path else None,
                tags=tags,
                stance=stance,
            )
            inbox_path = self._write_inbox_note(record)
            record["inbox_path"] = relative_path(inbox_path, self.settings.project_root)
            self._insert_capture(record)
            self._queue_capture_processing(capture_id, stage="warm")
            return self._public_capture(record)

    def save_clipboard_capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = (payload.get("copied_text") or "").strip()
        if not text:
            raise ValueError("copied_text is required")

        created_at = utc_now()
        capture_id = f"cap_{uuid.uuid4().hex[:12]}"
        source_app = (payload.get("source_app") or "clipboard").strip() or "clipboard"
        user_note = (payload.get("user_note") or "").strip() or None
        sensitivity = classify_sensitivity(
            source_type="clipboard",
            sensitivity_override=payload.get("sensitivity_override"),
        )
        stance = infer_stance(" ".join(filter(None, [source_app, text, user_note or ""])))

        with self._lock:
            raw_path = self._write_raw_capture(
                capture_id=capture_id,
                created_at=created_at,
                source_type="clipboard",
                selected_text=text,
                user_note=user_note,
                metadata={
                    "id": capture_id,
                    "created_at": created_at.isoformat(),
                    "source_type": "clipboard",
                    "page_url": None,
                    "page_title": None,
                    "source_app": source_app,
                    "is_public_source": False,
                    "sensitivity": sensitivity,
                    "tags_json": [],
                    "stance": stance,
                },
                slug_seed=source_app,
            )
            record = self._build_hot_capture_record(
                capture_id=capture_id,
                source_type="clipboard",
                created_at=created_at.isoformat(),
                selected_text=text,
                page_url=None,
                page_title=None,
                source_app=source_app,
                user_note=user_note,
                is_public_source=False,
                sensitivity=sensitivity,
                raw_path=relative_path(raw_path, self.settings.project_root),
                snapshot_path=None,
                tags=[],
                stance=stance,
            )
            inbox_path = self._write_inbox_note(record)
            record["inbox_path"] = relative_path(inbox_path, self.settings.project_root)
            self._insert_capture(record)
            self._queue_capture_processing(capture_id, stage="warm")
            return self._public_capture(record)

    def save_capture_review(self, capture_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        review_note = (payload.get("review_note") or "").strip() or None
        review_tags = self._dedupe_terms(payload.get("review_tags") or [])
        stance_override = payload.get("stance_override")

        with self._lock:
            row = self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            if row is None:
                raise KeyError(capture_id)
            self._connection.execute(
                """
                UPDATE captures
                SET review_note = ?, review_tags_json = ?, stance_override = ?,
                    stance = COALESCE(?, stance), processing_stage = 'queued'
                WHERE id = ?
                """,
                (review_note, json_dumps(review_tags), stance_override, stance_override, capture_id),
            )
            updated_row = self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            assert updated_row is not None
            record = self._row_to_record(updated_row)
            self._replace_capture_fts(record)
            self._write_inbox_note(record)
            self._queue_capture_processing(capture_id, stage="warm")
            return self._public_capture(record)

    def mark_capture_private(self, capture_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            if row is None:
                raise KeyError(capture_id)

            snapshot_path = row["snapshot_path"]
            if snapshot_path:
                resolved = self.settings.project_root / snapshot_path
                if resolved.exists():
                    resolved.unlink()

            self._connection.execute(
                """
                UPDATE captures
                SET sensitivity = 'sensitive', is_public_source = 0, snapshot_path = NULL, processing_stage = 'queued'
                WHERE id = ?
                """,
                (capture_id,),
            )
            updated_row = self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            assert updated_row is not None
            record = self._row_to_record(updated_row)
            self._write_inbox_note(record)
            self._queue_capture_processing(capture_id, stage="cold")
            return self._public_capture(record)

    def get_capture(self, capture_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        if row is None:
            return None
        return self._public_capture(self._row_to_record(row))

    def search(self, query: str, *, limit: int = 12) -> list[dict[str, Any]]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        with self._lock:
            lexical_meta = self._fts_rankings(cleaned_query)
            profile_weights = self._read_ai_artifact("profile_weights") or self._rebuild_profile_weights_locked()
            rows = self._connection.execute(
                """
                SELECT *
                FROM captures
                ORDER BY created_at DESC
                """
            ).fetchall()

        rows_by_id = {row["id"]: row for row in rows}
        dense_meta = self._dense_rankings(cleaned_query, rows)
        candidate_ids = set(lexical_meta) | set(dense_meta)
        hits: list[dict[str, Any]] = []
        now = utc_now()
        for capture_id in candidate_ids:
            row = rows_by_id.get(capture_id)
            if row is None:
                continue

            lexical_rank = lexical_meta.get(capture_id, {}).get("rank")
            dense_rank = dense_meta.get(capture_id, {}).get("rank")
            rrf_score = 0.0
            if lexical_rank is not None:
                rrf_score += 1.0 / (60.0 + lexical_rank)
            if dense_rank is not None:
                rrf_score += 1.0 / (60.0 + dense_rank)

            recency_bonus = self._recency_score(row["created_at"], now) * 0.04
            profile_bonus = self._profile_relevance_score(cleaned_query, row, profile_weights)
            total_score = rrf_score + recency_bonus + profile_bonus
            if total_score <= 0.0:
                continue

            reasons = []
            if lexical_rank is not None:
                reasons.append("matched exact terms")
            dense_score = dense_meta.get(capture_id, {}).get("score", 0.0)
            if dense_score >= 0.25:
                reasons.append("semantic overlap")
            if recency_bonus >= 0.004:
                reasons.append("recent capture")
            if profile_bonus:
                reasons.append("aligned with your working profile")
            if row["processing_stage"] != "ready":
                reasons.append("still enriching")
            if row["stance"] == "opposing":
                reasons.append("cautionary or opposing evidence")
            elif row["stance"] == "supporting":
                reasons.append("explicitly marked supportive")

            title = row["page_title"] or row["source_app"] or row["page_url"] or row["id"]
            snippet = snippet_for_query(
                " ".join(
                    filter(
                        None,
                        [
                            row["selected_text"],
                            row["user_note"] or "",
                            row["review_note"] or "",
                            row["page_title"] or "",
                        ],
                    )
                ),
                cleaned_query,
            )
            hits.append(
                {
                    "id": row["id"],
                    "title": title,
                    "snippet": snippet,
                    "source_label": row["page_title"] or row["source_app"] or row["page_url"] or row["source_type"],
                    "page_url": row["page_url"],
                    "raw_path": row["raw_path"],
                    "snapshot_path": row["snapshot_path"],
                    "created_at": row["created_at"],
                    "score": round(total_score, 4),
                    "reasons": reasons or ["relevant capture"],
                    "suggested_tags": self._dedupe_terms(
                        json_loads(row["suggested_tags_json"], []) + json_loads(row["review_tags_json"], [])
                    ),
                    "stance": row["stance"],
                }
            )

        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:limit]

    def get_profile(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            approved_rows = self._connection.execute(
                """
                SELECT *
                FROM profile_facets
                ORDER BY approved_at DESC, created_at DESC
                """
            ).fetchall()
            pending_rows = self._connection.execute(
                """
                SELECT *
                FROM profile_suggestions
                WHERE status = 'pending'
                ORDER BY confidence DESC, created_at DESC
                """
            ).fetchall()

        approved = [
            {
                "id": row["id"],
                "facet_type": row["facet_type"],
                "label": row["label"],
                "claim_text": row["claim_text"],
                "evidence_capture_ids": json_loads(row["evidence_capture_ids_json"], []),
                "approved_at": row["approved_at"],
            }
            for row in approved_rows
        ]
        pending = [
            {
                "id": row["id"],
                "facet_type": row["facet_type"],
                "label": row["label"],
                "claim_text": row["claim_text"],
                "rationale": row["rationale"],
                "confidence": row["confidence"],
                "evidence_capture_ids": json_loads(row["evidence_capture_ids_json"], []),
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in pending_rows
        ]
        return {"approved": approved, "pending": pending}

    def approve_profile_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM profile_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
            if row is None:
                raise KeyError(suggestion_id)
            now = utc_now().isoformat()
            facet_id = f"facet_{uuid.uuid4().hex[:12]}"
            self._connection.execute(
                """
                INSERT INTO profile_facets (
                    id, facet_type, label, claim_text, value_json,
                    evidence_capture_ids_json, approved_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    facet_id,
                    row["facet_type"],
                    row["label"],
                    row["claim_text"],
                    json_dumps({"label": row["label"], "claim_text": row["claim_text"]}),
                    row["evidence_capture_ids_json"],
                    now,
                    row["created_at"],
                    now,
                ),
            )
            self._connection.execute(
                "UPDATE profile_suggestions SET status = 'approved', updated_at = ? WHERE id = ?",
                (now, suggestion_id),
            )
            self._connection.commit()
            self._write_profile_markdown()
            self._rebuild_profile_weights_locked()
            self._rebuild_safe_profile_locked()
            self._rebuild_active_now_locked()
            self._rebuild_share_policies_locked()
        return self.get_profile()

    def reject_profile_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE profile_suggestions SET status = 'rejected', updated_at = ? WHERE id = ?",
                (utc_now().isoformat(), suggestion_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(suggestion_id)
            self._connection.commit()
            self._write_profile_markdown()
            self._rebuild_profile_weights_locked()
            self._rebuild_safe_profile_locked()
            self._rebuild_share_policies_locked()
        return self.get_profile()

    def get_safe_profile(self) -> dict[str, Any]:
        with self._lock:
            payload = self._read_ai_artifact("safe_profile")
            if payload:
                return payload
            return self._rebuild_safe_profile_locked()

    def get_active_now(self) -> dict[str, Any]:
        with self._lock:
            payload = self._read_ai_artifact("active_now")
            if payload:
                return payload
            return self._rebuild_active_now_locked()

    def get_share_policies(self) -> dict[str, Any]:
        with self._lock:
            payload = self._read_ai_artifact("share_policies")
            if payload:
                return payload
            return self._rebuild_share_policies_locked()

    def search_topic_cards(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        cleaned_query = query.strip().lower()
        with self._lock:
            rows = self._connection.execute("SELECT * FROM topic_cards ORDER BY activity_score DESC, updated_at DESC").fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        query_terms = set(extract_keyphrases(cleaned_query, limit=6)) if cleaned_query else set()
        query_tokens = {token for token in normalize_text(cleaned_query).split() if len(token) >= 3} if cleaned_query else set()
        for row in rows:
            card = {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "supporting_capture_ids": json_loads(row["supporting_capture_ids_json"], []),
                "opposing_capture_ids": json_loads(row["opposing_capture_ids_json"], []),
                "support_count": row["support_count"],
                "oppose_count": row["oppose_count"],
                "activity_score": row["activity_score"],
                "updated_at": row["updated_at"],
            }
            if not cleaned_query:
                scored.append((card["activity_score"], card))
                continue
            haystack = normalize_text(" ".join([card["title"], card["summary"]]))
            haystack_terms = set(extract_keyphrases(haystack, limit=8))
            haystack_tokens = set(haystack.split())
            overlap = len(query_terms & haystack_terms)
            overlap += len(query_tokens & haystack_tokens)
            if cleaned_query in haystack:
                overlap += 2
            if overlap <= 0:
                continue
            scored.append((card["activity_score"] + overlap * 0.25, card))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def build_ai_context_pack(self, *, query: str, max_items: int, mode: str) -> dict[str, Any]:
        self.run_pending_jobs()
        safe_profile = self.get_safe_profile()
        active_now = self.get_active_now()
        topic_query = query or " ".join(active_now.get("recent_topics", []))
        topic_cards = self.search_topic_cards(topic_query, limit=max_items)
        if not topic_cards and query.strip():
            fallback_query = " ".join(active_now.get("recent_topics", []))
            if fallback_query:
                topic_cards = self.search_topic_cards(fallback_query, limit=max_items)
        if not topic_cards:
            topic_cards = self.search_topic_cards("", limit=max_items)
        results = self.search(query or topic_query, limit=max_items * 4) if (query or topic_query) else []
        opposing_target = self._opposing_target(max_items=max_items, mode=mode)
        opposing = [item for item in results if item["stance"] == "opposing"][:opposing_target]
        supporting = [item for item in results if item["stance"] != "opposing"][: max_items - len(opposing)]
        if len(supporting) < max_items - len(opposing):
            overflow = [item for item in results if item["stance"] == "opposing" and item["id"] not in {hit["id"] for hit in opposing}]
            supporting.extend(overflow[: max(0, max_items - len(opposing) - len(supporting))])

        summary = active_now["summary"] if not query.strip() else f"Prepared AI context for: {query.strip()}"
        lines = [
            "Use this context about me before answering:",
            "",
            safe_profile["summary"].strip(),
            "",
            active_now["summary"].strip(),
        ]
        if supporting:
            lines.extend(["", "Relevant notes:"])
            for note in supporting[:max_items]:
                lines.append(f"- {note['title']}: {note['snippet']}")
        if opposing:
            lines.extend(["", "Counterarguments or cautionary notes:"])
            for note in opposing[:opposing_target]:
                lines.append(f"- {note['title']}: {note['snippet']}")
        else:
            lines.extend(["", "Counterarguments or cautionary notes:", "- No explicit opposing evidence was found for this topic in MouseKB yet."])
        if topic_cards:
            lines.extend(["", "Relevant topic cards:"])
            for card in topic_cards:
                lines.append(f"- {card['title']}: {card['summary']}")
        lines.extend(
            [
                "",
                "Privacy rule: this context is sanitized. Do not assume access to my raw notes unless I explicitly attach them.",
            ]
        )
        share_text = "\n".join(lines).strip() + "\n"
        return {
            "id": f"aictx_{uuid.uuid4().hex[:12]}",
            "query": query.strip(),
            "summary": summary,
            "share_text": share_text,
            "safe_profile": safe_profile,
            "active_now": active_now,
            "topic_cards": topic_cards,
        }

    def save_chat_wrapup(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_app = (payload.get("source_app") or "ai-chat").strip() or "ai-chat"
        conversation_title = (payload.get("conversation_title") or "").strip() or None
        source_url = (payload.get("source_url") or "").strip() or None
        user_note = (payload.get("user_note") or "").strip() or None
        messages = payload.get("messages") or []
        message_texts = [
            (message.get("content") or "").strip()
            for message in messages
            if isinstance(message, dict) and (message.get("content") or "").strip()
        ]
        if not message_texts:
            raise ValueError("messages are required")

        structured = self._summarize_chat_wrapup(message_texts)
        summary_parts = [structured["summary"]]
        if structured["action_items"]:
            summary_parts.append("Action items: " + "; ".join(structured["action_items"][:4]))
        if structured["unresolved_questions"]:
            summary_parts.append("Open questions: " + "; ".join(structured["unresolved_questions"][:3]))
        summary_text = "\n\n".join(part for part in summary_parts if part).strip()

        capture = self.save_clipboard_capture(
            {
                "copied_text": summary_text,
                "source_app": f"{source_app} wrap-up",
                "user_note": user_note,
                "sensitivity_override": "private",
            }
        )

        created_at = utc_now().isoformat()
        wrapup_id = f"wrap_{uuid.uuid4().hex[:12]}"
        inbox_path = self._write_chat_wrapup_note(
            wrapup_id=wrapup_id,
            created_at=created_at,
            capture_id=capture["id"],
            source_app=source_app,
            conversation_title=conversation_title,
            source_url=source_url,
            structured=structured,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO chat_wrapups (
                    id, capture_id, source_app, source_url, conversation_title, summary,
                    decisions_json, action_items_json, unresolved_questions_json,
                    lessons_json, inbox_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wrapup_id,
                    capture["id"],
                    source_app,
                    source_url,
                    conversation_title,
                    structured["summary"],
                    json_dumps(structured["decisions"]),
                    json_dumps(structured["action_items"]),
                    json_dumps(structured["unresolved_questions"]),
                    json_dumps(structured["lessons"]),
                    relative_path(inbox_path, self.settings.project_root),
                    created_at,
                ),
            )
            self._connection.commit()

        return {
            "id": wrapup_id,
            "capture_id": capture["id"],
            "source_app": source_app,
            "conversation_title": conversation_title,
            "summary": structured["summary"],
            "decisions": structured["decisions"],
            "action_items": structured["action_items"],
            "unresolved_questions": structured["unresolved_questions"],
            "lessons": structured["lessons"],
            "inbox_path": relative_path(inbox_path, self.settings.project_root),
            "created_at": created_at,
        }

    def run_pending_jobs(self, *, max_jobs: int | None = None) -> dict[str, int]:
        processed = 0
        failed = 0
        while max_jobs is None or processed < max_jobs:
            with self._lock:
                job = self._connection.execute(
                    """
                    SELECT id, capture_id, stage
                    FROM processing_jobs
                    WHERE status = 'pending'
                    ORDER BY scheduled_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                if job is None:
                    break
                self._connection.execute(
                    "UPDATE processing_jobs SET status = 'processing', attempts = attempts + 1 WHERE id = ?",
                    (job["id"],),
                )
                self._connection.commit()

            try:
                if job["stage"] == "warm":
                    self._process_warm_capture(job["capture_id"])
                else:
                    self._process_cold_capture(job["capture_id"])
            except Exception as exc:  # pragma: no cover - exercised via status and logs
                with self._lock:
                    self._connection.execute(
                        """
                        UPDATE processing_jobs
                        SET status = 'failed', error_text = ?, processed_at = ?
                        WHERE id = ?
                        """,
                        (str(exc), utc_now().isoformat(), job["id"]),
                    )
                    self._connection.commit()
                failed += 1
            else:
                with self._lock:
                    self._connection.execute(
                        "UPDATE processing_jobs SET status = 'done', processed_at = ? WHERE id = ?",
                        (utc_now().isoformat(), job["id"]),
                    )
                    self._connection.commit()
                processed += 1
        return {"processed_jobs": processed, "failed_jobs": failed}

    def reindex_from_markdown(self) -> dict[str, int]:
        with self._lock:
            self._connection.execute("DELETE FROM captures")
            self._connection.execute("DELETE FROM captures_fts")
            self._connection.execute("DELETE FROM processing_jobs")
            self._connection.execute("DELETE FROM profile_suggestions")
            self._connection.execute("DELETE FROM topic_cards")
            self._connection.execute("DELETE FROM ai_artifacts")
            self._connection.execute("DELETE FROM chat_wrapups")
            raw_files = [path for path in self.settings.raw_dir.rglob("*.md") if not path.name.endswith("--snapshot.md")]
            capture_ids: list[str] = []
            count = 0
            for path in sorted(raw_files):
                parsed = parse_capture_markdown(path.read_text(encoding="utf-8"))
                meta = parsed["meta"]
                if not meta.get("id"):
                    continue
                record = self._build_hot_capture_record(
                    capture_id=meta["id"],
                    source_type=meta.get("source_type", "clipboard"),
                    created_at=meta.get("created_at"),
                    selected_text=parsed["selected_text"],
                    page_url=meta.get("page_url"),
                    page_title=meta.get("page_title"),
                    source_app=meta.get("source_app"),
                    user_note=parsed.get("user_note"),
                    is_public_source=bool(meta.get("is_public_source")),
                    sensitivity=meta.get("sensitivity", "private"),
                raw_path=relative_path(path, self.settings.project_root),
                snapshot_path=self._snapshot_relative_path(meta["id"], meta.get("created_at")),
                tags=self._dedupe_terms(meta.get("tags_json") or []),
                stance=meta.get("stance") or "neutral",
            )
                record["inbox_path"] = relative_path(self._expected_inbox_path(meta["id"]), self.settings.project_root)
                self._insert_capture(record)
                capture_ids.append(meta["id"])
                count += 1
            for capture_id in capture_ids:
                self._enqueue_job(capture_id, "warm")
            self._connection.commit()

        self.run_pending_jobs()
        return {"reindexed_captures": count}

    def _build_hot_capture_record(
        self,
        *,
        capture_id: str,
        source_type: str,
        created_at: str,
        selected_text: str,
        page_url: str | None,
        page_title: str | None,
        source_app: str | None,
        user_note: str | None,
        is_public_source: bool,
        sensitivity: str,
        raw_path: str,
        snapshot_path: str | None,
        tags: list[str],
        stance: str,
    ) -> dict[str, Any]:
        return {
            "id": capture_id,
            "source_type": source_type,
            "created_at": created_at,
            "selected_text": selected_text,
            "page_url": page_url,
            "page_title": page_title,
            "source_app": source_app,
            "user_note": user_note,
            "review_note": None,
            "is_public_source": is_public_source,
            "sensitivity": sensitivity,
            "raw_path": raw_path,
            "inbox_path": "",
            "snapshot_path": snapshot_path,
            "tags": self._dedupe_terms(tags),
            "review_tags": [],
            "suggested_tags": self._dedupe_terms(tags),
            "suggested_topics": [],
            "suggested_folder": None,
            "duplicate_of_capture_id": None,
            "related_capture_ids": [],
            "stance": stance,
            "stance_override": None,
            "embedding": [],
            "processing_stage": "queued",
        }

    def _init_db(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    selected_text TEXT NOT NULL,
                    page_url TEXT,
                    page_title TEXT,
                    source_app TEXT,
                    user_note TEXT,
                    review_note TEXT,
                    is_public_source INTEGER NOT NULL DEFAULT 0,
                    sensitivity TEXT NOT NULL,
                    raw_path TEXT NOT NULL,
                    inbox_path TEXT NOT NULL,
                    snapshot_path TEXT,
                    tags_json TEXT NOT NULL,
                    review_tags_json TEXT NOT NULL DEFAULT '[]',
                    suggested_tags_json TEXT NOT NULL,
                    suggested_topics_json TEXT NOT NULL,
                    suggested_folder TEXT,
                    duplicate_of_capture_id TEXT,
                    related_capture_ids_json TEXT NOT NULL,
                    stance TEXT NOT NULL DEFAULT 'neutral',
                    stance_override TEXT,
                    embedding_json TEXT NOT NULL,
                    processing_stage TEXT NOT NULL DEFAULT 'ready'
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
                    capture_id UNINDEXED,
                    selected_text,
                    user_note,
                    page_title,
                    page_url,
                    source_app,
                    tags_text
                );

                CREATE TABLE IF NOT EXISTS profile_suggestions (
                    id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    facet_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    claim_text TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_capture_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_facets (
                    id TEXT PRIMARY KEY,
                    facet_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    claim_text TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    evidence_capture_ids_json TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS processing_jobs (
                    id TEXT PRIMARY KEY,
                    capture_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_text TEXT,
                    scheduled_at TEXT NOT NULL,
                    processed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ai_artifacts (
                    name TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS topic_cards (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    supporting_capture_ids_json TEXT NOT NULL,
                    opposing_capture_ids_json TEXT NOT NULL,
                    support_count INTEGER NOT NULL DEFAULT 0,
                    oppose_count INTEGER NOT NULL DEFAULT 0,
                    activity_score REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_wrapups (
                    id TEXT PRIMARY KEY,
                    capture_id TEXT NOT NULL,
                    source_app TEXT NOT NULL,
                    source_url TEXT,
                    conversation_title TEXT,
                    summary TEXT NOT NULL,
                    decisions_json TEXT NOT NULL,
                    action_items_json TEXT NOT NULL,
                    unresolved_questions_json TEXT NOT NULL,
                    lessons_json TEXT NOT NULL,
                    inbox_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_capture_columns()
            self._connection.commit()

    def _ensure_capture_columns(self) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(captures)").fetchall()
        }
        if "review_note" not in columns:
            self._connection.execute("ALTER TABLE captures ADD COLUMN review_note TEXT")
        if "review_tags_json" not in columns:
            self._connection.execute("ALTER TABLE captures ADD COLUMN review_tags_json TEXT NOT NULL DEFAULT '[]'")
        if "processing_stage" not in columns:
            self._connection.execute("ALTER TABLE captures ADD COLUMN processing_stage TEXT NOT NULL DEFAULT 'ready'")
        if "stance" not in columns:
            self._connection.execute("ALTER TABLE captures ADD COLUMN stance TEXT NOT NULL DEFAULT 'neutral'")
            self._connection.execute(
                "UPDATE captures SET stance = CASE WHEN contrarian = 1 THEN 'opposing' ELSE 'neutral' END"
            )
        if "stance_override" not in columns:
            self._connection.execute("ALTER TABLE captures ADD COLUMN stance_override TEXT")

        topic_columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(topic_cards)").fetchall()
        }
        if "support_count" not in topic_columns:
            self._connection.execute("ALTER TABLE topic_cards ADD COLUMN support_count INTEGER NOT NULL DEFAULT 0")
        if "oppose_count" not in topic_columns:
            self._connection.execute("ALTER TABLE topic_cards ADD COLUMN oppose_count INTEGER NOT NULL DEFAULT 0")

    def _insert_capture(self, record: dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO captures (
                id, source_type, created_at, selected_text, page_url, page_title,
                source_app, user_note, review_note, is_public_source, sensitivity,
                raw_path, inbox_path, snapshot_path, tags_json, review_tags_json,
                suggested_tags_json, suggested_topics_json, suggested_folder,
                duplicate_of_capture_id, related_capture_ids_json, stance, stance_override,
                embedding_json, processing_stage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["source_type"],
                record["created_at"],
                record["selected_text"],
                record["page_url"],
                record["page_title"],
                record["source_app"],
                record["user_note"],
                record["review_note"],
                1 if record["is_public_source"] else 0,
                record["sensitivity"],
                record["raw_path"],
                record["inbox_path"],
                record["snapshot_path"],
                json_dumps(record["tags"]),
                json_dumps(record["review_tags"]),
                json_dumps(record["suggested_tags"]),
                json_dumps(record["suggested_topics"]),
                record["suggested_folder"],
                record["duplicate_of_capture_id"],
                json_dumps(record["related_capture_ids"]),
                record["stance"],
                record["stance_override"],
                json_dumps(record["embedding"]),
                record["processing_stage"],
            ),
        )
        self._replace_capture_fts(record)
        self._connection.commit()

    def _replace_capture_fts(self, record: dict[str, Any]) -> None:
        self._connection.execute("DELETE FROM captures_fts WHERE capture_id = ?", (record["id"],))
        self._connection.execute(
            """
            INSERT INTO captures_fts (
                capture_id, selected_text, user_note, page_title, page_url,
                source_app, tags_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["selected_text"],
                self._compose_note_text(record),
                record["page_title"] or "",
                record["page_url"] or "",
                record["source_app"] or "",
                " ".join(self._dedupe_terms(record["tags"] + record["review_tags"] + record["suggested_tags"])),
            ),
        )
        self._connection.commit()

    def _fts_rankings(self, query: str) -> dict[str, dict[str, float]]:
        escaped_query = " ".join(
            f'"{part}"'
            for part in query.replace('"', " ").split()
            if part
        )
        if not escaped_query:
            return {}
        rows = self._connection.execute(
            """
            SELECT capture_id, bm25(captures_fts, 8.0, 4.0, 2.0, 1.0, 1.0, 1.5) AS rank
            FROM captures_fts
            WHERE captures_fts MATCH ?
            ORDER BY rank
            LIMIT 40
            """,
            (escaped_query,),
        ).fetchall()
        rankings: dict[str, dict[str, float]] = {}
        for index, row in enumerate(rows, start=1):
            rankings[row["capture_id"]] = {
                "rank": float(index),
                "score": 1.0 / (1.0 + abs(row["rank"])),
            }
        return rankings

    def _dense_rankings(self, query: str, rows: list[sqlite3.Row]) -> dict[str, dict[str, float]]:
        query_embedding = self._embed_text(query)
        if not query_embedding:
            return {}

        scored: list[tuple[float, str]] = []
        for row in rows:
            embedding = json_loads(row["embedding_json"], [])
            if not embedding:
                continue
            similarity = max(0.0, cosine_similarity(query_embedding, embedding))
            if similarity <= 0.12:
                continue
            scored.append((similarity, row["id"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return {
            capture_id: {"rank": float(index), "score": score}
            for index, (score, capture_id) in enumerate(scored[:40], start=1)
        }

    def _embed_text(self, text: str) -> list[float] | None:
        return self._embeddings.embed_text(text)

    def _write_raw_capture(
        self,
        *,
        capture_id: str,
        created_at: datetime,
        source_type: str,
        selected_text: str,
        user_note: str | None,
        metadata: dict[str, Any],
        slug_seed: str,
    ) -> Path:
        capture_dir = self.settings.raw_dir / created_at.strftime("%Y") / created_at.strftime("%m") / created_at.strftime("%d")
        capture_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(slug_seed, fallback=source_type)
        raw_path = capture_dir / f"{created_at.strftime('%H%M%S')}-{slug}-{capture_id}.md"
        raw_path.write_text(
            build_capture_markdown(metadata, selected_text=selected_text, user_note=user_note),
            encoding="utf-8",
        )
        return raw_path

    def _write_snapshot(
        self,
        *,
        capture_id: str,
        created_at: datetime,
        page_title: str,
        page_url: str,
        markdown: str,
    ) -> Path:
        capture_dir = self.settings.raw_dir / created_at.strftime("%Y") / created_at.strftime("%m") / created_at.strftime("%d")
        capture_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = capture_dir / f"{created_at.strftime('%H%M%S')}-{capture_id}--snapshot.md"
        snapshot_path.write_text(
            build_snapshot_markdown(title=page_title, source_url=page_url, body_markdown=markdown),
            encoding="utf-8",
        )
        return snapshot_path

    def _expected_inbox_path(self, capture_id: str) -> Path:
        return self.settings.inbox_dir / f"{capture_id}.md"

    def _expected_wrapup_path(self, wrapup_id: str) -> Path:
        return self.settings.inbox_dir / f"{wrapup_id}.md"

    def _snapshot_relative_path(self, capture_id: str, created_at: str | None) -> str | None:
        if not created_at:
            return None
        parsed = datetime.fromisoformat(created_at)
        capture_dir = self.settings.raw_dir / parsed.strftime("%Y") / parsed.strftime("%m") / parsed.strftime("%d")
        candidates = list(capture_dir.glob(f"*-{capture_id}--snapshot.md"))
        if not candidates:
            return None
        return relative_path(candidates[0], self.settings.project_root)

    def _write_inbox_note(self, record: dict[str, Any]) -> Path:
        inbox_path = self._expected_inbox_path(record["id"])
        title = record["page_title"] or record["source_app"] or record["id"]
        lines = [
            f"# Inbox: {title}",
            "",
            f"- Capture ID: {record['id']}",
            f"- Source type: {record['source_type']}",
            f"- Created: {record['created_at']}",
            f"- Sensitivity: {record['sensitivity']}",
            f"- Stance: {record['stance']}",
            f"- Processing: {record['processing_stage']}",
            f"- Raw path: {record['raw_path']}",
        ]
        if record.get("page_url"):
            lines.append(f"- URL: {record['page_url']}")
        if record.get("snapshot_path"):
            lines.append(f"- Snapshot path: {record['snapshot_path']}")
        lines.extend(["", "## Selected Text", "", record["selected_text"].strip(), ""])
        if record.get("user_note"):
            lines.extend(["## Capture Note", "", record["user_note"].strip(), ""])
        if record.get("review_note"):
            lines.extend(["## Review Note", "", record["review_note"].strip(), ""])

        review_tags = record.get("review_tags") or []
        suggested_tags_lines = [f"- {tag}" for tag in record["suggested_tags"]] or ["- processing"]
        review_tag_lines = [f"- {tag}" for tag in review_tags] or ["- none yet"]
        suggested_topic_lines = [f"- {topic}" for topic in record["suggested_topics"]] or ["- processing"]
        lines.extend(
            [
                "## Review Tags",
                "",
                *review_tag_lines,
                "",
                "## Suggested Tags",
                "",
                *suggested_tags_lines,
                "",
                "## Suggested Topics",
                "",
                *suggested_topic_lines,
                "",
            ]
        )
        if record.get("suggested_folder"):
            lines.extend(["## Suggested Folder", "", record["suggested_folder"], ""])
        if record.get("duplicate_of_capture_id"):
            lines.extend(["## Duplicate Candidate", "", record["duplicate_of_capture_id"], ""])
        if record.get("related_capture_ids"):
            lines.extend(["## Related Captures", "", *[f"- {value}" for value in record["related_capture_ids"]], ""])

        inbox_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return inbox_path

    def _write_chat_wrapup_note(
        self,
        *,
        wrapup_id: str,
        created_at: str,
        capture_id: str,
        source_app: str,
        conversation_title: str | None,
        source_url: str | None,
        structured: dict[str, Any],
    ) -> Path:
        inbox_path = self._expected_wrapup_path(wrapup_id)
        lines = [
            f"# Chat Wrap-up: {conversation_title or source_app}",
            "",
            f"- Wrap-up ID: {wrapup_id}",
            f"- Source app: {source_app}",
            f"- Capture ID: {capture_id}",
            f"- Created: {created_at}",
        ]
        if source_url:
            lines.append(f"- URL: {source_url}")
        lines.extend(["", "## Summary", "", structured["summary"], ""])
        sections = [
            ("Decisions", structured["decisions"]),
            ("Action Items", structured["action_items"]),
            ("Unresolved Questions", structured["unresolved_questions"]),
            ("Lessons", structured["lessons"]),
        ]
        for title, items in sections:
            lines.extend([f"## {title}", ""])
            if items:
                lines.extend([f"- {item}" for item in items])
            else:
                lines.append("- none")
            lines.append("")
        inbox_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return inbox_path

    def _find_related_captures(
        self,
        text: str,
        *,
        page_url: str | None = None,
        exclude_capture_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized = normalize_text(text)
        embedding = self._embed_text(text)
        phrase_set = set(extract_keyphrases(text, limit=8))
        rows = self._connection.execute(
            """
            SELECT id, page_url, selected_text, embedding_json
            FROM captures
            ORDER BY created_at DESC
            LIMIT 200
            """
        ).fetchall()
        related = []
        for row in rows:
            if exclude_capture_id and row["id"] == exclude_capture_id:
                continue
            prior_text = normalize_text(row["selected_text"])
            prior_embedding = json_loads(row["embedding_json"], [])
            similarity = 0.0
            if embedding and prior_embedding:
                similarity = cosine_similarity(embedding, prior_embedding)
            else:
                overlap = phrase_set & set(extract_keyphrases(row["selected_text"], limit=8))
                similarity = min(0.8, len(overlap) * 0.18)
            if prior_text == normalized or (page_url and row["page_url"] == page_url and prior_text == normalized):
                related.append({"id": row["id"], "score": 1.0})
            elif similarity >= 0.32:
                related.append({"id": row["id"], "score": similarity})
        related.sort(key=lambda item: item["score"], reverse=True)
        return related[:6]

    def _build_capture_suggestions(
        self,
        *,
        text: str,
        title: str,
        existing_tags: list[str],
        prior_matches: list[dict[str, Any]],
        note_text: str = "",
    ) -> dict[str, Any]:
        phrases = extract_keyphrases(" ".join(filter(None, [title, text, note_text])), limit=6)
        suggested_tags = self._dedupe_terms(existing_tags + phrases[:4])
        suggested_topics = self._dedupe_terms(phrases[:6])
        suggested_folder = f"topic/{slugify(suggested_tags[0], fallback='inbox')}" if suggested_tags else "topic/inbox"
        duplicate_of = prior_matches[0]["id"] if prior_matches and prior_matches[0]["score"] >= 0.95 else None
        related_capture_ids = [match["id"] for match in prior_matches if match["score"] < 0.95][:3]
        cues = detect_reasoning_cues(" ".join(filter(None, [title, text, note_text])))
        return {
            "suggested_tags": suggested_tags,
            "suggested_topics": suggested_topics,
            "suggested_folder": suggested_folder,
            "duplicate_of_capture_id": duplicate_of,
            "related_capture_ids": related_capture_ids,
            "stance": "opposing" if cues["contrarian_interest"] else "neutral",
        }

    def _queue_capture_processing(self, capture_id: str, *, stage: str) -> None:
        with self._lock:
            self._enqueue_job(capture_id, stage)
            self._connection.commit()
        self._kick_background_worker()

    def _enqueue_job(self, capture_id: str, stage: str) -> None:
        existing = self._connection.execute(
            """
            SELECT id
            FROM processing_jobs
            WHERE capture_id = ? AND stage = ? AND status IN ('pending', 'processing')
            """,
            (capture_id, stage),
        ).fetchone()
        if existing is not None:
            return
        self._connection.execute(
            """
            INSERT INTO processing_jobs (
                id, capture_id, stage, status, attempts, error_text, scheduled_at, processed_at
            ) VALUES (?, ?, ?, 'pending', 0, NULL, ?, NULL)
            """,
            (f"job_{uuid.uuid4().hex[:12]}", capture_id, stage, utc_now().isoformat()),
        )

    def _kick_background_worker(self) -> None:
        with self._worker_state_lock:
            if self._worker_running:
                return
            self._worker_running = True
        thread = threading.Thread(target=self._background_worker_loop, name="mousekb-worker", daemon=True)
        thread.start()

    def _background_worker_loop(self) -> None:
        try:
            self.run_pending_jobs()
        finally:
            with self._worker_state_lock:
                self._worker_running = False
            with self._lock:
                pending = self._connection.execute(
                    "SELECT 1 FROM processing_jobs WHERE status = 'pending' LIMIT 1"
                ).fetchone()
            if pending is not None:
                self._kick_background_worker()

    def _process_warm_capture(self, capture_id: str) -> None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            if row is None:
                return
            record = self._row_to_record(row)
            existing_tags = self._dedupe_terms(record["tags"] + record["review_tags"])
            note_text = " ".join(filter(None, [record.get("user_note"), record.get("review_note")]))
            prior_matches = self._find_related_captures(
                record["selected_text"],
                page_url=record["page_url"],
                exclude_capture_id=record["id"],
            )
            suggestions = self._build_capture_suggestions(
                text=record["selected_text"],
                title=record["page_title"] or record["source_app"] or record["id"],
                existing_tags=existing_tags,
                prior_matches=prior_matches,
                note_text=note_text,
            )
            embedding = self._embed_text(
                " ".join(
                    filter(
                        None,
                        [
                            record.get("page_title"),
                            record["selected_text"],
                            record.get("user_note") or "",
                            record.get("review_note") or "",
                            record.get("source_app"),
                        ],
                    )
                )
            ) or []
            record.update(
                {
                    "suggested_tags": suggestions["suggested_tags"],
                    "suggested_topics": suggestions["suggested_topics"],
                    "suggested_folder": suggestions["suggested_folder"],
                    "duplicate_of_capture_id": suggestions["duplicate_of_capture_id"],
                    "related_capture_ids": suggestions["related_capture_ids"],
                    "stance": infer_stance(
                        " ".join(
                            filter(
                                None,
                                [
                                    record.get("page_title"),
                                    record["selected_text"],
                                    record.get("user_note") or "",
                                    record.get("review_note") or "",
                                    record.get("source_app"),
                                ],
                            )
                        ),
                        stance_override=record.get("stance_override"),
                    ),
                    "embedding": embedding,
                    "processing_stage": "cold-pending",
                }
            )
            self._connection.execute(
                """
                UPDATE captures
                SET suggested_tags_json = ?, suggested_topics_json = ?, suggested_folder = ?,
                    duplicate_of_capture_id = ?, related_capture_ids_json = ?, stance = ?, stance_override = ?,
                    embedding_json = ?, processing_stage = ?
                WHERE id = ?
                """,
                (
                    json_dumps(record["suggested_tags"]),
                    json_dumps(record["suggested_topics"]),
                    record["suggested_folder"],
                    record["duplicate_of_capture_id"],
                    json_dumps(record["related_capture_ids"]),
                    record["stance"],
                    record["stance_override"],
                    json_dumps(record["embedding"]),
                    record["processing_stage"],
                    record["id"],
                ),
            )
            self._replace_capture_fts(record)
            self._write_inbox_note(record)
            self._upsert_profile_suggestions(record)
            self._write_profile_markdown()
            self._rebuild_profile_weights_locked()
            self._rebuild_active_now_locked()
            self._rebuild_share_policies_locked()
            self._enqueue_job(capture_id, "cold")
            self._connection.commit()

    def _process_cold_capture(self, capture_id: str) -> None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            if row is None:
                return
            self._connection.execute(
                "UPDATE captures SET processing_stage = 'ready' WHERE id = ?",
                (capture_id,),
            )
            record = self._row_to_record(self._connection.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone())
            self._write_inbox_note(record)
            self._rebuild_topic_cards_locked()
            self._rebuild_profile_weights_locked()
            self._rebuild_safe_profile_locked()
            self._rebuild_active_now_locked()
            self._rebuild_share_policies_locked()
            self._connection.commit()

    def _upsert_profile_suggestions(self, record: dict[str, Any]) -> None:
        text_blob = " ".join(
            filter(
                None,
                [
                    record.get("page_title"),
                    record["selected_text"],
                    record.get("user_note") or "",
                    record.get("review_note") or "",
                    record.get("source_app"),
                ],
            )
        )
        cues = detect_reasoning_cues(text_blob)
        tag_counter = self._global_tag_counter(record["suggested_tags"] + record["review_tags"])
        proposals = []

        for tag in self._dedupe_terms(record["suggested_tags"] + record["review_tags"])[:3]:
            if tag_counter[tag] >= 2:
                proposals.append(
                    {
                        "facet_type": "domain",
                        "label": tag,
                        "claim_text": f"You repeatedly collect material about {tag}.",
                        "rationale": "This topic has appeared in multiple captures and looks like a working domain.",
                        "confidence": min(0.92, 0.45 + tag_counter[tag] * 0.12),
                    }
                )
                proposals.append(
                    {
                        "facet_type": "recurring_topic",
                        "label": tag,
                        "claim_text": f"{tag} is becoming a recurring topic in your knowledge base.",
                        "rationale": "The same concept keeps resurfacing across saved material.",
                        "confidence": min(0.88, 0.4 + tag_counter[tag] * 0.1),
                    }
                )
                proposals.append(
                    {
                        "facet_type": "knowledge_level",
                        "label": tag,
                        "claim_text": f"You likely already have working context in {tag} and may prefer answers that skip basic setup.",
                        "rationale": "Repeated saves in the same domain suggest prior familiarity rather than one-off curiosity.",
                        "confidence": min(0.8, 0.36 + tag_counter[tag] * 0.08),
                    }
                )

        if cues["evidence_preference"]:
            proposals.append(
                {
                    "facet_type": "evidence_preference",
                    "label": "evidence-backed",
                    "claim_text": "You prefer claims to be backed by evidence, citations, data, or source material.",
                    "rationale": "This capture contains strong evidence-seeking language.",
                    "confidence": 0.78,
                }
            )
        if cues["first_principles"]:
            proposals.append(
                {
                    "facet_type": "reasoning_style",
                    "label": "first-principles",
                    "claim_text": "You often want ideas broken down from first principles rather than accepted at face value.",
                    "rationale": "This capture uses first-principles language directly.",
                    "confidence": 0.76,
                }
            )
        if cues["contrarian_interest"]:
            proposals.append(
                {
                    "facet_type": "contrarian_interest",
                    "label": "counterarguments",
                    "claim_text": "You intentionally keep opposing or skeptical material around to pressure-test conclusions.",
                    "rationale": "This capture looks explicitly contrarian or counterargument-seeking.",
                    "confidence": 0.83,
                }
            )
            proposals.append(
                {
                    "facet_type": "reasoning_style",
                    "label": "counterarguments",
                    "claim_text": "You seem to value counterarguments and anti-cases when reasoning through a topic.",
                    "rationale": "Opposing material is a repeated signal of how you like to think.",
                    "confidence": 0.71,
                }
            )

        seen_keys = set()
        for proposal in proposals:
            dedupe_key = f"{proposal['facet_type']}::{slugify(proposal['label'])}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            self._upsert_profile_suggestion(dedupe_key=dedupe_key, capture_id=record["id"], proposal=proposal)

    def _upsert_profile_suggestion(self, *, dedupe_key: str, capture_id: str, proposal: dict[str, Any]) -> None:
        existing = self._connection.execute(
            "SELECT * FROM profile_suggestions WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()
        now = utc_now().isoformat()
        if existing is None:
            self._connection.execute(
                """
                INSERT INTO profile_suggestions (
                    id, dedupe_key, facet_type, label, claim_text, rationale,
                    confidence, evidence_capture_ids_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    f"ps_{uuid.uuid4().hex[:12]}",
                    dedupe_key,
                    proposal["facet_type"],
                    proposal["label"],
                    proposal["claim_text"],
                    proposal["rationale"],
                    proposal["confidence"],
                    json_dumps([capture_id]),
                    now,
                    now,
                ),
            )
            self._connection.commit()
            return

        if existing["status"] == "rejected":
            return

        evidence_ids = json_loads(existing["evidence_capture_ids_json"], [])
        if capture_id not in evidence_ids:
            evidence_ids.append(capture_id)
        updated_confidence = max(existing["confidence"], proposal["confidence"])
        self._connection.execute(
            """
            UPDATE profile_suggestions
            SET claim_text = ?, rationale = ?, confidence = ?, evidence_capture_ids_json = ?, updated_at = ?
            WHERE dedupe_key = ?
            """,
            (
                proposal["claim_text"],
                proposal["rationale"],
                updated_confidence,
                json_dumps(evidence_ids),
                now,
                dedupe_key,
            ),
        )
        self._connection.commit()

    def _global_tag_counter(self, pending_tags: list[str]) -> Counter[str]:
        counter: Counter[str] = Counter(self._dedupe_terms(pending_tags))
        rows = self._connection.execute("SELECT suggested_tags_json, review_tags_json FROM captures").fetchall()
        for row in rows:
            for tag in self._dedupe_terms(json_loads(row["suggested_tags_json"], []) + json_loads(row["review_tags_json"], [])):
                counter[tag] += 1
        return counter

    def _write_profile_markdown(self) -> None:
        profile = self.get_profile()
        approved_lines = ["# Approved Profile Facets", ""]
        if not profile["approved"]:
            approved_lines.append("No approved profile facets yet.")
        else:
            for facet in profile["approved"]:
                approved_lines.extend(
                    [
                        f"## {facet['facet_type'].replace('_', ' ').title()}",
                        "",
                        f"- Label: {facet['label']}",
                        f"- Claim: {facet['claim_text']}",
                        f"- Evidence: {', '.join(facet['evidence_capture_ids'])}",
                        f"- Approved at: {facet['approved_at']}",
                        "",
                    ]
                )
        self.settings.approved_profile_path.write_text("\n".join(approved_lines).rstrip() + "\n", encoding="utf-8")

        pending_lines = ["# Pending Profile Suggestions", ""]
        if not profile["pending"]:
            pending_lines.append("No pending profile suggestions.")
        else:
            for facet in profile["pending"]:
                pending_lines.extend(
                    [
                        f"## {facet['facet_type'].replace('_', ' ').title()}",
                        "",
                        f"- Label: {facet['label']}",
                        f"- Claim: {facet['claim_text']}",
                        f"- Confidence: {facet['confidence']:.2f}",
                        f"- Evidence: {', '.join(facet['evidence_capture_ids'])}",
                        f"- Rationale: {facet['rationale']}",
                        "",
                    ]
                )
        self.settings.pending_profile_path.write_text("\n".join(pending_lines).rstrip() + "\n", encoding="utf-8")

    def _read_ai_artifact(self, name: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_json FROM ai_artifacts WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return json_loads(row["payload_json"], {})

    def _write_ai_artifact(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        updated_at = payload.get("updated_at") or utc_now().isoformat()
        payload["updated_at"] = updated_at
        self._connection.execute(
            """
            INSERT INTO ai_artifacts (name, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
            """,
            (name, json_dumps(payload), updated_at),
        )
        self._connection.commit()
        return payload

    def _rebuild_profile_weights_locked(self) -> dict[str, Any]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM captures
            ORDER BY created_at DESC
            LIMIT 200
            """
        ).fetchall()

        now = utc_now()
        topic_affinity: Counter[str] = Counter()
        topic_familiarity: Counter[str] = Counter()
        evidence_seeking = 0.0
        counterargument_seeking = 0.0

        for row in rows:
            text_blob = " ".join(
                filter(
                    None,
                    [
                        row["page_title"],
                        row["selected_text"],
                        row["user_note"] or "",
                        row["review_note"] or "",
                        row["source_app"],
                    ],
                )
            )
            cues = detect_reasoning_cues(text_blob)
            recency_weight = 1.0 + self._recency_score(row["created_at"], now) * 2.5
            tags = self._dedupe_terms(
                json_loads(row["suggested_tags_json"], []) + json_loads(row["review_tags_json"], [])
            )
            if not tags:
                tags = extract_keyphrases(text_blob, limit=3)

            for tag in tags[:3]:
                topic_affinity[tag] += recency_weight
                topic_familiarity[tag] += 1.0 + (0.4 if cues["knowledge_level"] else 0.0)

            if cues["evidence_preference"]:
                evidence_seeking += recency_weight
            if row["stance"] == "opposing" or cues["contrarian_interest"]:
                counterargument_seeking += recency_weight

        max_affinity = max(topic_affinity.values(), default=1.0)
        max_familiarity = max(topic_familiarity.values(), default=1.0)
        payload = {
            "updated_at": utc_now().isoformat(),
            "topic_affinity": {
                tag: round(score / max_affinity, 4)
                for tag, score in topic_affinity.most_common(12)
            },
            "topic_familiarity": {
                tag: round(score / max_familiarity, 4)
                for tag, score in topic_familiarity.most_common(12)
            },
            "evidence_seeking": round(min(1.0, evidence_seeking / 4.0), 4),
            "counterargument_seeking": round(min(1.0, counterargument_seeking / 4.0), 4),
        }
        return self._write_ai_artifact("profile_weights", payload)

    def _rebuild_active_now_locked(self) -> dict[str, Any]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM captures
            WHERE sensitivity != 'sensitive'
            ORDER BY created_at DESC
            LIMIT 30
            """
        ).fetchall()
        topic_counter: Counter[str] = Counter()
        topic_evidence: dict[str, list[str]] = defaultdict(list)
        open_loops: list[str] = []
        for row in rows:
            tags = self._dedupe_terms(
                json_loads(row["suggested_tags_json"], []) + json_loads(row["review_tags_json"], [])
            )
            if not tags:
                tags = extract_keyphrases(
                    " ".join(filter(None, [row["page_title"], row["selected_text"], row["review_note"] or ""])),
                    limit=3,
                )
            for tag in tags[:3]:
                topic_counter[tag] += 1
                if row["id"] not in topic_evidence[tag]:
                    topic_evidence[tag].append(row["id"])
            open_loops.extend(self._extract_action_like_lines([row["review_note"] or "", row["user_note"] or ""]))

        current_projects = [
            {
                "label": tag,
                "score": float(score),
                "evidence_capture_ids": topic_evidence[tag][:4],
            }
            for tag, score in topic_counter.most_common(5)
        ]
        recent_topics = [item["label"] for item in current_projects[:5]]
        open_loops = self._dedupe_lines(open_loops)[:6]
        summary_lines = []
        if current_projects:
            summary_lines.append(
                "Current focus areas: " + ", ".join(item["label"] for item in current_projects[:4]) + "."
            )
        if open_loops:
            summary_lines.append("Open loops: " + "; ".join(open_loops[:3]) + ".")
        if not summary_lines:
            summary_lines.append("No strong current-work signal yet. Save a few things and MouseKB will build it up.")

        share_text = "\n".join(
            [
                "Current context about what I am working through right now:",
                *[f"- {line}" for line in summary_lines],
                "",
                "Use this as helpful background, but ask before assuming private specifics I have not explicitly shared.",
            ]
        ).strip() + "\n"
        payload = {
            "updated_at": utc_now().isoformat(),
            "summary": " ".join(summary_lines),
            "share_text": share_text,
            "current_projects": current_projects,
            "open_loops": open_loops,
            "recent_topics": recent_topics,
        }
        return self._write_ai_artifact("active_now", payload)

    def _rebuild_safe_profile_locked(self) -> dict[str, Any]:
        profile = self.get_profile()
        profile_weights = self._read_ai_artifact("profile_weights") or self._rebuild_profile_weights_locked()
        approved = profile["approved"]
        pending = [item for item in profile["pending"] if item["confidence"] >= 0.72][:4]
        source_facets = approved or pending

        facet_rows = []
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in source_facets:
            grouped[item["facet_type"]].append(item["label"])
            facet_rows.append(
                {
                    "facet_type": item["facet_type"],
                    "label": item["label"],
                    "claim_text": item["claim_text"],
                    "confidence": float(item.get("confidence", 1.0)),
                    "evidence_capture_ids": item["evidence_capture_ids"],
                }
            )

        lines = []
        if grouped.get("knowledge_level"):
            lines.append(
                "Assume I probably already know the basics in: " + ", ".join(grouped["knowledge_level"][:3]) + "."
            )
        if grouped.get("domain"):
            lines.append("Recurring domains: " + ", ".join(grouped["domain"][:4]) + ".")
        if grouped.get("evidence_preference"):
            lines.append("Prefer evidence-backed answers with citations or source-grounded reasoning.")
        elif profile_weights.get("evidence_seeking", 0.0) >= 0.6:
            lines.append("Prefer evidence-backed answers with citations or source-grounded reasoning.")
        if grouped.get("reasoning_style"):
            lines.append("Reasoning style: " + ", ".join(grouped["reasoning_style"][:3]) + ".")
        if grouped.get("contrarian_interest"):
            lines.append("Include opposing cases or objections when relevant.")
        elif profile_weights.get("counterargument_seeking", 0.0) >= 0.55:
            lines.append("Include opposing cases or objections when relevant.")
        if not lines:
            lines.append("Keep answers concise, practical, and grounded in evidence when possible.")

        summary = " ".join(lines)
        share_text = "\n".join(
            [
                "Before answering, assume this about me:",
                *[f"- {line}" for line in lines],
                "",
                "Do not infer personal details beyond this sanitized profile unless I explicitly share them.",
            ]
        ).strip() + "\n"
        custom_instructions_text = "\n".join(
            [
                "Use this as stable context about how to help me:",
                *[f"- {line}" for line in lines],
                "- Do not over-explain basics when my prior context suggests familiarity.",
                "- Prefer clear evidence, proofs, objections, and source-backed reasoning.",
            ]
        ).strip()
        payload = {
            "updated_at": utc_now().isoformat(),
            "summary": summary,
            "share_text": share_text,
            "custom_instructions_text": custom_instructions_text,
            "facets": facet_rows,
        }
        return self._write_ai_artifact("safe_profile", payload)

    def _rebuild_share_policies_locked(self) -> dict[str, Any]:
        payload = {
            "updated_at": utc_now().isoformat(),
            "default_mode": "safe-derived-only",
            "rules": [
                "Share sanitized profile, active topics, and compact topic summaries by default.",
                "Never expose raw note bodies or full private chat transcripts automatically.",
                "Use compact evidence IDs and recency markers instead of raw excerpts wherever possible.",
            ],
            "explicit_share_required": [
                "raw captures",
                "private note bodies",
                "full AI chat transcripts",
                "page snapshots from marked-private captures",
            ],
        }
        return self._write_ai_artifact("share_policies", payload)

    def _rebuild_topic_cards_locked(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM captures
            WHERE sensitivity != 'sensitive'
            ORDER BY created_at DESC
            """
        ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            tags = self._dedupe_terms(json_loads(row["suggested_tags_json"], []) + json_loads(row["review_tags_json"], []))
            if not tags:
                tags = extract_keyphrases(" ".join(filter(None, [row["page_title"], row["selected_text"]])), limit=2)
            for tag in tags[:3]:
                grouped[tag].append(row)

        self._connection.execute("DELETE FROM topic_cards")
        cards: list[dict[str, Any]] = []
        for slug, group in grouped.items():
            if len(group) < 2:
                continue
            supporting = [row["id"] for row in group if row["stance"] != "opposing"][:6]
            opposing = [row["id"] for row in group if row["stance"] == "opposing"][:6]
            title = slug
            related_terms = Counter[str]()
            for row in group[:10]:
                for term in extract_keyphrases(
                    " ".join(filter(None, [row["page_title"], row["selected_text"], row["review_note"] or ""])),
                    limit=4,
                ):
                    if term != slug:
                        related_terms[term] += 1
            summary_bits = [f"Recurring topic across {len(group)} captures."]
            if related_terms:
                summary_bits.append("Often connected to " + ", ".join(term for term, _ in related_terms.most_common(3)) + ".")
            if opposing:
                summary_bits.append("Includes opposing or cautionary material.")
            summary = " ".join(summary_bits)
            card = {
                "id": f"topic_{slugify(slug)}",
                "title": title,
                "summary": summary,
                "supporting_capture_ids": supporting,
                "opposing_capture_ids": opposing,
                "support_count": len([row for row in group if row["stance"] != "opposing"]),
                "oppose_count": len([row for row in group if row["stance"] == "opposing"]),
                "activity_score": round(float(len(group)) + len(opposing) * 0.25, 3),
                "updated_at": utc_now().isoformat(),
            }
            self._connection.execute(
                """
                INSERT INTO topic_cards (
                    id, title, summary, supporting_capture_ids_json,
                    opposing_capture_ids_json, support_count, oppose_count, activity_score, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["id"],
                    card["title"],
                    card["summary"],
                    json_dumps(card["supporting_capture_ids"]),
                    json_dumps(card["opposing_capture_ids"]),
                    card["support_count"],
                    card["oppose_count"],
                    card["activity_score"],
                    card["updated_at"],
                ),
            )
            cards.append(card)
        self._connection.commit()
        return cards

    def _summarize_chat_wrapup(self, message_texts: list[str]) -> dict[str, Any]:
        recent = [text for text in message_texts[-12:] if text]
        sentences = self._extract_sentences(recent)
        summary = " ".join(sentences[:3]).strip()
        if not summary:
            summary = recent[-1][:400].strip()
        decisions = self._dedupe_lines(
            [
                sentence
                for sentence in sentences
                if any(
                    cue in sentence.lower()
                    for cue in ("we will", "i will", "we should", "let's", "decided", "decision", "use ")
                )
            ]
        )[:5]
        action_items = self._dedupe_lines(self._extract_action_like_lines(recent))[:6]
        unresolved = self._dedupe_lines(
            [sentence for sentence in sentences if sentence.endswith("?") or "not sure" in sentence.lower() or "unclear" in sentence.lower()]
        )[:5]
        lessons = self._dedupe_lines(
            [
                sentence
                for sentence in sentences
                if any(cue in sentence.lower() for cue in ("important", "prefer", "learned", "because", "works better"))
            ]
        )[:5]
        return {
            "summary": summary or "Conversation wrap-up saved.",
            "decisions": decisions,
            "action_items": action_items,
            "unresolved_questions": unresolved,
            "lessons": lessons,
        }

    def _extract_sentences(self, text_parts: list[str]) -> list[str]:
        sentences: list[str] = []
        for part in text_parts:
            for raw in part.replace("\n", " ").split("."):
                sentence = " ".join(raw.split()).strip()
                if len(sentence) < 24:
                    continue
                if not sentence.endswith("?"):
                    sentence = sentence.rstrip("!,:;")
                sentences.append(sentence + ("?" if raw.strip().endswith("?") else "."))
        return sentences

    def _extract_action_like_lines(self, text_parts: list[str]) -> list[str]:
        candidates: list[str] = []
        for part in text_parts:
            for raw in part.splitlines():
                line = " ".join(raw.split()).strip(" -\t")
                lowered = line.lower()
                if len(line) < 12:
                    continue
                if any(cue in lowered for cue in ("todo", "next step", "need to", "follow up", "ship", "implement", "fix", "check")):
                    candidates.append(line.rstrip("."))
        return candidates

    def _dedupe_lines(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            normalized = normalize_text(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(item)
        return ordered

    def _compose_note_text(self, record: dict[str, Any]) -> str:
        return "\n\n".join(
            part for part in [record.get("user_note") or "", record.get("review_note") or ""] if part.strip()
        ).strip()

    def _dedupe_terms(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = normalize_text(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "source_type": row["source_type"],
            "created_at": row["created_at"],
            "selected_text": row["selected_text"],
            "page_url": row["page_url"],
            "page_title": row["page_title"],
            "source_app": row["source_app"],
            "user_note": row["user_note"],
            "review_note": row["review_note"],
            "is_public_source": bool(row["is_public_source"]),
            "sensitivity": row["sensitivity"],
            "raw_path": row["raw_path"],
            "inbox_path": row["inbox_path"],
            "snapshot_path": row["snapshot_path"],
            "tags": json_loads(row["tags_json"], []),
            "review_tags": json_loads(row["review_tags_json"], []),
            "suggested_tags": json_loads(row["suggested_tags_json"], []),
            "suggested_topics": json_loads(row["suggested_topics_json"], []),
            "suggested_folder": row["suggested_folder"],
            "duplicate_of_capture_id": row["duplicate_of_capture_id"],
            "related_capture_ids": json_loads(row["related_capture_ids_json"], []),
            "stance": row["stance"] or "neutral",
            "stance_override": row["stance_override"],
            "embedding": json_loads(row["embedding_json"], []),
            "processing_stage": row["processing_stage"],
        }

    def _public_capture(self, record: dict[str, Any]) -> dict[str, Any]:
        public = dict(record)
        public.pop("embedding", None)
        public.pop("stance_override", None)
        return public

    def _recency_score(self, created_at: str, now: datetime) -> float:
        age_seconds = max(0.0, (now - datetime.fromisoformat(created_at)).total_seconds())
        days = age_seconds / 86400.0
        return max(0.0, 0.2 - min(days / 90.0, 0.2))

    def _profile_relevance_score(self, query: str, row: sqlite3.Row, profile_weights: dict[str, Any]) -> float:
        if not profile_weights:
            return 0.0

        query_terms = set(extract_keyphrases(query, limit=6))
        query_terms.update(token for token in normalize_text(query).split() if len(token) >= 3)
        capture_tags = self._dedupe_terms(
            json_loads(row["suggested_tags_json"], []) + json_loads(row["review_tags_json"], [])
        )

        topic_affinity = profile_weights.get("topic_affinity", {})
        topic_familiarity = profile_weights.get("topic_familiarity", {})
        score = 0.0
        for tag in capture_tags[:4]:
            if query_terms and not any(tag in term or term in tag for term in query_terms):
                continue
            score += topic_affinity.get(tag, 0.0) * 0.004
            score += topic_familiarity.get(tag, 0.0) * 0.003

        text_blob = " ".join(filter(None, [row["page_title"], row["selected_text"], row["review_note"] or ""]))
        cues = detect_reasoning_cues(text_blob)
        if cues["evidence_preference"]:
            score += float(profile_weights.get("evidence_seeking", 0.0)) * 0.003
        if row["stance"] == "opposing":
            score += float(profile_weights.get("counterargument_seeking", 0.0)) * 0.004
        return min(0.012, score)

    def _opposing_target(self, *, max_items: int, mode: str) -> int:
        if max_items <= 0:
            return 0
        if mode == "support-heavy":
            return 1 if max_items >= 3 else 0
        if mode == "opposition-heavy":
            return max(1, math.ceil(max_items * 0.5))
        return max(1, math.ceil(max_items * 0.3))
