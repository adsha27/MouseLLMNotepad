from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .heuristics import (
    classify_sensitivity,
    cosine_similarity,
    detect_reasoning_cues,
    extract_keyphrases,
    hashed_embedding,
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
        self._connection = sqlite3.connect(self.settings.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._init_db()
        self._write_profile_markdown()

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

        with self._lock:
            prior_matches = self._find_related_captures(text, page_url=page_url)
            suggestions = self._build_capture_suggestions(
                text=text,
                title=page_title,
                existing_tags=tags,
                prior_matches=prior_matches,
            )
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
                    "suggested_tags_json": suggestions["suggested_tags"],
                    "suggested_topics_json": suggestions["suggested_topics"],
                    "suggested_folder": suggestions["suggested_folder"],
                    "duplicate_of_capture_id": suggestions["duplicate_of_capture_id"],
                    "related_capture_ids_json": suggestions["related_capture_ids"],
                    "contrarian": suggestions["contrarian"],
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

            record = {
                "id": capture_id,
                "source_type": "browser",
                "created_at": created_at.isoformat(),
                "selected_text": text,
                "page_url": page_url,
                "page_title": page_title,
                "source_app": None,
                "user_note": user_note,
                "is_public_source": is_public_source,
                "sensitivity": sensitivity,
                "raw_path": relative_path(raw_path, self.settings.project_root),
                "inbox_path": "",
                "snapshot_path": relative_path(snapshot_path, self.settings.project_root) if snapshot_path else None,
                "tags": tags,
                "suggested_tags": suggestions["suggested_tags"],
                "suggested_topics": suggestions["suggested_topics"],
                "suggested_folder": suggestions["suggested_folder"],
                "duplicate_of_capture_id": suggestions["duplicate_of_capture_id"],
                "related_capture_ids": suggestions["related_capture_ids"],
                "contrarian": suggestions["contrarian"],
                "embedding": hashed_embedding(" ".join(filter(None, [page_title, text, user_note or ""]))),
            }
            inbox_path = self._write_inbox_note(record)
            record["inbox_path"] = relative_path(inbox_path, self.settings.project_root)

            self._insert_capture(record)
            self._upsert_profile_suggestions(record)
            self._write_profile_markdown()
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

        with self._lock:
            prior_matches = self._find_related_captures(text)
            suggestions = self._build_capture_suggestions(
                text=text,
                title=source_app,
                existing_tags=[],
                prior_matches=prior_matches,
            )
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
                    "suggested_tags_json": suggestions["suggested_tags"],
                    "suggested_topics_json": suggestions["suggested_topics"],
                    "suggested_folder": suggestions["suggested_folder"],
                    "duplicate_of_capture_id": suggestions["duplicate_of_capture_id"],
                    "related_capture_ids_json": suggestions["related_capture_ids"],
                    "contrarian": suggestions["contrarian"],
                },
                slug_seed=source_app,
            )
            record = {
                "id": capture_id,
                "source_type": "clipboard",
                "created_at": created_at.isoformat(),
                "selected_text": text,
                "page_url": None,
                "page_title": None,
                "source_app": source_app,
                "user_note": user_note,
                "is_public_source": False,
                "sensitivity": sensitivity,
                "raw_path": relative_path(raw_path, self.settings.project_root),
                "inbox_path": "",
                "snapshot_path": None,
                "tags": [],
                "suggested_tags": suggestions["suggested_tags"],
                "suggested_topics": suggestions["suggested_topics"],
                "suggested_folder": suggestions["suggested_folder"],
                "duplicate_of_capture_id": suggestions["duplicate_of_capture_id"],
                "related_capture_ids": suggestions["related_capture_ids"],
                "contrarian": suggestions["contrarian"],
                "embedding": hashed_embedding(" ".join(filter(None, [source_app, text, user_note or ""]))),
            }
            inbox_path = self._write_inbox_note(record)
            record["inbox_path"] = relative_path(inbox_path, self.settings.project_root)

            self._insert_capture(record)
            self._upsert_profile_suggestions(record)
            self._write_profile_markdown()
            return self._public_capture(record)

    def search(self, query: str, *, limit: int = 12) -> list[dict[str, Any]]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        with self._lock:
            lexical_scores = self._fts_scores(cleaned_query)
            query_embedding = hashed_embedding(cleaned_query)
            approved_terms = self._approved_profile_terms()
            rows = self._connection.execute(
                """
                SELECT *
                FROM captures
                ORDER BY created_at DESC
                """
            ).fetchall()

        hits: list[dict[str, Any]] = []
        now = utc_now()
        for row in rows:
            embedding = json_loads(row["embedding_json"], [])
            semantic_score = max(0.0, cosine_similarity(query_embedding, embedding))
            lexical_score = lexical_scores.get(row["id"], 0.0)
            recency_score = self._recency_score(row["created_at"], now)
            profile_score = self._profile_relevance_score(query, row, approved_terms)
            total_score = lexical_score + semantic_score + recency_score + profile_score
            if total_score <= 0:
                continue

            reasons = []
            if lexical_score:
                reasons.append("matched exact terms")
            if semantic_score >= 0.18:
                reasons.append("semantic overlap")
            if recency_score >= 0.08:
                reasons.append("recent capture")
            if profile_score:
                reasons.append("aligned with approved profile")

            title = row["page_title"] or row["source_app"] or row["page_url"] or row["id"]
            snippet = snippet_for_query(
                " ".join(filter(None, [row["selected_text"], row["user_note"] or "", row["page_title"] or ""])),
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
                    "suggested_tags": json_loads(row["suggested_tags_json"], []),
                    "contrarian": bool(row["contrarian"]),
                }
            )

        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:limit]

    def build_context_pack(self, *, query: str, include_raw_note_ids: list[str], max_items: int, mode: str) -> dict[str, Any]:
        results = self.search(query, limit=max_items * 4)
        if mode == "support-heavy":
            support_limit = max_items
            opposing_limit = max(1, max_items // 3)
        elif mode == "opposition-heavy":
            support_limit = max(1, max_items // 2)
            opposing_limit = max_items
        else:
            support_limit = max_items
            opposing_limit = max(2, max_items // 2)

        supporting = [item for item in results if not item["contrarian"]][:support_limit]
        opposing = [item for item in results if item["contrarian"]][:opposing_limit]
        explicit_raw = [self.get_capture(note_id) for note_id in include_raw_note_ids if self.get_capture(note_id)]

        profile_summary = self.profile_summary_text()
        export_lines = [
            f"# MouseKB Context Pack",
            "",
            f"Query: {query.strip()}",
            f"Generated: {utc_now().isoformat()}",
            "",
            "## Profile Summary",
            "",
            profile_summary or "No approved profile facets yet.",
            "",
            "## Supporting Notes",
            "",
        ]
        export_lines.extend(self._format_note_section(supporting))
        export_lines.extend(["", "## Opposing / Cautionary Notes", ""])
        export_lines.extend(self._format_note_section(opposing))

        if explicit_raw:
            export_lines.extend(["", "## Explicit Raw Notes", ""])
            for capture in explicit_raw:
                export_lines.extend(
                    [
                        f"### {capture['page_title'] or capture['source_app'] or capture['id']}",
                        "",
                        capture["selected_text"],
                        "",
                    ]
                )
                if capture.get("snapshot_path"):
                    snapshot_path = self.settings.project_root / capture["snapshot_path"]
                    if snapshot_path.exists():
                        export_lines.extend(
                            [
                                "#### Attached Snapshot",
                                "",
                                snapshot_path.read_text(encoding="utf-8").strip(),
                                "",
                            ]
                        )

        context_id = f"ctx_{uuid.uuid4().hex[:12]}"
        export_text = "\n".join(export_lines).strip() + "\n"
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO context_packs (
                    id, query, mode, include_raw_ids_json, supporting_note_ids_json,
                    opposing_note_ids_json, export_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context_id,
                    query.strip(),
                    mode,
                    json_dumps(include_raw_note_ids),
                    json_dumps([item["id"] for item in supporting]),
                    json_dumps([item["id"] for item in opposing]),
                    export_text,
                    utc_now().isoformat(),
                ),
            )
            self._connection.commit()

        return {
            "id": context_id,
            "query": query.strip(),
            "profile_summary": profile_summary,
            "supporting_notes": supporting,
            "opposing_notes": opposing,
            "export_text": export_text,
        }

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
            row = self._connection.execute(
                "SELECT * FROM profile_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
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
                """
                UPDATE profile_suggestions
                SET status = 'approved', updated_at = ?
                WHERE id = ?
                """,
                (now, suggestion_id),
            )
            self._connection.commit()
        self._write_profile_markdown()
        return self.get_profile()

    def reject_profile_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE profile_suggestions
                SET status = 'rejected', updated_at = ?
                WHERE id = ?
                """,
                (utc_now().isoformat(), suggestion_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(suggestion_id)
            self._connection.commit()
        self._write_profile_markdown()
        return self.get_profile()

    def get_capture(self, capture_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM captures WHERE id = ?",
                (capture_id,),
            ).fetchone()
        if row is None:
            return None
        return self._public_capture(self._row_to_record(row))

    def reindex_from_markdown(self) -> dict[str, int]:
        with self._lock:
            self._connection.execute("DELETE FROM captures")
            self._connection.execute("DELETE FROM captures_fts")
            raw_files = [path for path in self.settings.raw_dir.rglob("*.md") if not path.name.endswith("--snapshot.md")]
            count = 0
            for path in sorted(raw_files):
                parsed = parse_capture_markdown(path.read_text(encoding="utf-8"))
                meta = parsed["meta"]
                if not meta.get("id"):
                    continue
                record = {
                    "id": meta["id"],
                    "source_type": meta.get("source_type", "clipboard"),
                    "created_at": meta.get("created_at"),
                    "selected_text": parsed["selected_text"],
                    "page_url": meta.get("page_url"),
                    "page_title": meta.get("page_title"),
                    "source_app": meta.get("source_app"),
                    "user_note": parsed.get("user_note"),
                    "is_public_source": bool(meta.get("is_public_source")),
                    "sensitivity": meta.get("sensitivity", "private"),
                    "raw_path": relative_path(path, self.settings.project_root),
                    "inbox_path": relative_path(self._expected_inbox_path(meta["id"]), self.settings.project_root),
                    "snapshot_path": self._snapshot_relative_path(meta["id"], meta.get("created_at")),
                    "tags": self._dedupe_terms(meta.get("tags_json") or []),
                    "suggested_tags": self._dedupe_terms(meta.get("suggested_tags_json") or []),
                    "suggested_topics": self._dedupe_terms(meta.get("suggested_topics_json") or []),
                    "suggested_folder": meta.get("suggested_folder"),
                    "duplicate_of_capture_id": meta.get("duplicate_of_capture_id"),
                    "related_capture_ids": self._dedupe_terms(meta.get("related_capture_ids_json") or []),
                    "contrarian": bool(meta.get("contrarian")),
                    "embedding": hashed_embedding(
                        " ".join(
                            filter(
                                None,
                                [meta.get("page_title"), parsed["selected_text"], parsed.get("user_note") or "", meta.get("source_app")],
                            )
                        )
                    ),
                }
                self._insert_capture(record)
                count += 1
            self._connection.commit()
        return {"reindexed_captures": count}

    def profile_summary_text(self) -> str:
        profile = self.get_profile()
        grouped: dict[str, list[str]] = defaultdict(list)
        for facet in profile["approved"]:
            grouped[facet["facet_type"]].append(facet["claim_text"])
        if not grouped:
            return ""

        lines = []
        for facet_type in sorted(grouped):
            label = facet_type.replace("_", " ").title()
            joined = "; ".join(grouped[facet_type])
            lines.append(f"- {label}: {joined}")
        return "\n".join(lines)

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
                    is_public_source INTEGER NOT NULL DEFAULT 0,
                    sensitivity TEXT NOT NULL,
                    raw_path TEXT NOT NULL,
                    inbox_path TEXT NOT NULL,
                    snapshot_path TEXT,
                    tags_json TEXT NOT NULL,
                    suggested_tags_json TEXT NOT NULL,
                    suggested_topics_json TEXT NOT NULL,
                    suggested_folder TEXT,
                    duplicate_of_capture_id TEXT,
                    related_capture_ids_json TEXT NOT NULL,
                    contrarian INTEGER NOT NULL DEFAULT 0,
                    embedding_json TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS context_packs (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    include_raw_ids_json TEXT NOT NULL,
                    supporting_note_ids_json TEXT NOT NULL,
                    opposing_note_ids_json TEXT NOT NULL,
                    export_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._connection.commit()

    def _insert_capture(self, record: dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO captures (
                id, source_type, created_at, selected_text, page_url, page_title,
                source_app, user_note, is_public_source, sensitivity, raw_path,
                inbox_path, snapshot_path, tags_json, suggested_tags_json,
                suggested_topics_json, suggested_folder, duplicate_of_capture_id,
                related_capture_ids_json, contrarian, embedding_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                1 if record["is_public_source"] else 0,
                record["sensitivity"],
                record["raw_path"],
                record["inbox_path"],
                record["snapshot_path"],
                json_dumps(record["tags"]),
                json_dumps(record["suggested_tags"]),
                json_dumps(record["suggested_topics"]),
                record["suggested_folder"],
                record["duplicate_of_capture_id"],
                json_dumps(record["related_capture_ids"]),
                1 if record["contrarian"] else 0,
                json_dumps(record["embedding"]),
            ),
        )
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
                record["user_note"] or "",
                record["page_title"] or "",
                record["page_url"] or "",
                record["source_app"] or "",
                " ".join(record["suggested_tags"]),
            ),
        )
        self._connection.commit()

    def _fts_scores(self, query: str) -> dict[str, float]:
        escaped_query = " ".join(part for part in query.replace('"', " ").split() if part)
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
        scores: dict[str, float] = {}
        for row in rows:
            rank = row["rank"]
            lexical_score = 1.0 / (1.0 + abs(rank))
            scores[row["capture_id"]] = lexical_score
        return scores

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
            f"- Raw path: {record['raw_path']}",
        ]
        if record.get("page_url"):
            lines.append(f"- URL: {record['page_url']}")
        if record.get("snapshot_path"):
            lines.append(f"- Snapshot path: {record['snapshot_path']}")
        lines.extend(
            [
                "",
                "## Selected Text",
                "",
                record["selected_text"].strip(),
                "",
            ]
        )
        if record.get("user_note"):
            lines.extend(["## User Note", "", record["user_note"].strip(), ""])
        suggested_tags_lines = [f"- {tag}" for tag in record["suggested_tags"]] or ["- none yet"]
        suggested_topic_lines = [f"- {topic}" for topic in record["suggested_topics"]] or ["- none yet"]
        lines.extend(
            [
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

    def _find_related_captures(self, text: str, *, page_url: str | None = None) -> list[dict[str, Any]]:
        normalized = normalize_text(text)
        embedding = hashed_embedding(text)
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
            prior_text = normalize_text(row["selected_text"])
            similarity = cosine_similarity(embedding, json_loads(row["embedding_json"], []))
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
    ) -> dict[str, Any]:
        phrases = extract_keyphrases(" ".join(filter(None, [title, text])), limit=6)
        suggested_tags = self._dedupe_terms(existing_tags + phrases[:4])
        suggested_topics = self._dedupe_terms(phrases[:6])
        suggested_folder = f"topic/{slugify(suggested_tags[0], fallback='inbox')}" if suggested_tags else "topic/inbox"
        duplicate_of = prior_matches[0]["id"] if prior_matches and prior_matches[0]["score"] >= 0.95 else None
        related_capture_ids = [match["id"] for match in prior_matches if match["score"] < 0.95][:3]
        cues = detect_reasoning_cues(" ".join(filter(None, [title, text])))
        return {
            "suggested_tags": suggested_tags,
            "suggested_topics": suggested_topics,
            "suggested_folder": suggested_folder,
            "duplicate_of_capture_id": duplicate_of,
            "related_capture_ids": related_capture_ids,
            "contrarian": cues["contrarian_interest"],
        }

    def _upsert_profile_suggestions(self, record: dict[str, Any]) -> None:
        text_blob = " ".join(
            filter(None, [record.get("page_title"), record["selected_text"], record.get("user_note") or "", record.get("source_app")])
        )
        cues = detect_reasoning_cues(text_blob)
        tag_counter = self._global_tag_counter(record["suggested_tags"])
        proposals = []

        for tag in record["suggested_tags"][:3]:
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
            self._upsert_profile_suggestion(
                dedupe_key=dedupe_key,
                capture_id=record["id"],
                proposal=proposal,
            )

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
        counter: Counter[str] = Counter(pending_tags)
        rows = self._connection.execute("SELECT suggested_tags_json FROM captures").fetchall()
        for row in rows:
            for tag in json_loads(row["suggested_tags_json"], []):
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
            "is_public_source": bool(row["is_public_source"]),
            "sensitivity": row["sensitivity"],
            "raw_path": row["raw_path"],
            "inbox_path": row["inbox_path"],
            "snapshot_path": row["snapshot_path"],
            "tags": json_loads(row["tags_json"], []),
            "suggested_tags": json_loads(row["suggested_tags_json"], []),
            "suggested_topics": json_loads(row["suggested_topics_json"], []),
            "suggested_folder": row["suggested_folder"],
            "duplicate_of_capture_id": row["duplicate_of_capture_id"],
            "related_capture_ids": json_loads(row["related_capture_ids_json"], []),
            "contrarian": bool(row["contrarian"]),
        }

    def _public_capture(self, record: dict[str, Any]) -> dict[str, Any]:
        public = dict(record)
        public.pop("embedding", None)
        return public

    def _recency_score(self, created_at: str, now: datetime) -> float:
        age_seconds = max(0.0, (now - datetime.fromisoformat(created_at)).total_seconds())
        days = age_seconds / 86400.0
        return max(0.0, 0.2 - min(days / 90.0, 0.2))

    def _approved_profile_terms(self) -> set[str]:
        rows = self._connection.execute(
            "SELECT label, claim_text FROM profile_facets",
        ).fetchall()
        terms = set()
        for row in rows:
            terms.update(extract_keyphrases(f"{row['label']} {row['claim_text']}", limit=6))
        return terms

    def _profile_relevance_score(self, query: str, row: sqlite3.Row, approved_terms: set[str]) -> float:
        if not approved_terms:
            return 0.0
        query_terms = set(extract_keyphrases(query, limit=6))
        capture_terms = set(json_loads(row["suggested_tags_json"], []))
        overlap = len((query_terms | capture_terms) & approved_terms)
        return min(0.18, overlap * 0.06)

    def _format_note_section(self, notes: list[dict[str, Any]]) -> list[str]:
        if not notes:
            return ["- none"]
        lines: list[str] = []
        for note in notes:
            lines.extend(
                [
                    f"### {note['title']}",
                    "",
                    f"- ID: {note['id']}",
                    f"- Source: {note['source_label']}",
                    f"- Raw path: {note['raw_path']}",
                    f"- Reasons: {', '.join(note['reasons'])}",
                    "",
                    note["snippet"],
                    "",
                ]
            )
        return lines

    def _dedupe_terms(self, values: list[str]) -> list[str]:
        cleaned = []
        seen = set()
        for value in values:
            normalized = normalize_text(str(value))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)
        return cleaned
