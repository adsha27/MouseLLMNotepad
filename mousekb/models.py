from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BrowserCaptureIn(BaseModel):
    selected_text: str
    page_url: str
    page_title: str
    page_snapshot_markdown: str | None = None
    is_public_source: bool = False
    user_note: str | None = None
    tags: list[str] = Field(default_factory=list)


class ClipboardCaptureIn(BaseModel):
    copied_text: str
    source_app: str | None = None
    user_note: str | None = None
    sensitivity_override: Literal["public", "private", "sensitive"] | None = None


class CaptureRecord(BaseModel):
    id: str
    source_type: Literal["browser", "clipboard"]
    created_at: str
    selected_text: str
    page_url: str | None = None
    page_title: str | None = None
    source_app: str | None = None
    user_note: str | None = None
    is_public_source: bool = False
    sensitivity: str
    raw_path: str
    inbox_path: str
    snapshot_path: str | None = None
    tags: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    suggested_topics: list[str] = Field(default_factory=list)
    suggested_folder: str | None = None
    duplicate_of_capture_id: str | None = None
    related_capture_ids: list[str] = Field(default_factory=list)
    contrarian: bool = False


class SearchHit(BaseModel):
    id: str
    title: str
    snippet: str
    source_label: str
    page_url: str | None = None
    raw_path: str
    snapshot_path: str | None = None
    created_at: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    contrarian: bool = False


class SearchResponse(BaseModel):
    query: str
    total: int
    items: list[SearchHit]


class ProfileFacet(BaseModel):
    id: str
    facet_type: str
    label: str
    claim_text: str
    evidence_capture_ids: list[str] = Field(default_factory=list)
    approved_at: str


class ProfileSuggestion(BaseModel):
    id: str
    facet_type: str
    label: str
    claim_text: str
    rationale: str
    confidence: float
    evidence_capture_ids: list[str] = Field(default_factory=list)
    status: str
    created_at: str
    updated_at: str


class ProfileResponse(BaseModel):
    approved: list[ProfileFacet]
    pending: list[ProfileSuggestion]


class ContextPackRequest(BaseModel):
    query: str
    include_raw_note_ids: list[str] = Field(default_factory=list)
    max_items: int = 6
    mode: Literal["balanced", "support-heavy", "opposition-heavy"] = "balanced"


class ContextPackResponse(BaseModel):
    id: str
    query: str
    profile_summary: str
    supporting_notes: list[SearchHit]
    opposing_notes: list[SearchHit]
    export_text: str


class HealthResponse(BaseModel):
    status: str
    bind: str
