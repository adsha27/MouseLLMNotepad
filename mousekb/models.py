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
    stance: Literal["neutral", "opposing", "supporting"] = "neutral"
    processing_stage: str = "ready"
    review_note: str | None = None
    review_tags: list[str] = Field(default_factory=list)


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
    stance: Literal["neutral", "opposing", "supporting"] = "neutral"


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


class HealthResponse(BaseModel):
    status: str
    bind: str


class CaptureReviewIn(BaseModel):
    review_note: str | None = None
    review_tags: list[str] = Field(default_factory=list)
    stance_override: Literal["neutral", "opposing", "supporting"] | None = None


class SafeProfileFacet(BaseModel):
    facet_type: str
    label: str
    claim_text: str
    confidence: float
    evidence_capture_ids: list[str] = Field(default_factory=list)


class SafeProfileResponse(BaseModel):
    updated_at: str
    summary: str
    share_text: str
    custom_instructions_text: str
    facets: list[SafeProfileFacet] = Field(default_factory=list)


class ActiveNowItem(BaseModel):
    label: str
    score: float
    evidence_capture_ids: list[str] = Field(default_factory=list)


class ActiveNowResponse(BaseModel):
    updated_at: str
    summary: str
    share_text: str
    current_projects: list[ActiveNowItem] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    recent_topics: list[str] = Field(default_factory=list)


class TopicCard(BaseModel):
    id: str
    title: str
    summary: str
    supporting_capture_ids: list[str] = Field(default_factory=list)
    opposing_capture_ids: list[str] = Field(default_factory=list)
    support_count: int = 0
    oppose_count: int = 0
    activity_score: float = 0.0
    updated_at: str


class TopicCardsResponse(BaseModel):
    query: str
    total: int
    items: list[TopicCard] = Field(default_factory=list)


class SharePoliciesResponse(BaseModel):
    updated_at: str
    default_mode: str
    rules: list[str] = Field(default_factory=list)
    explicit_share_required: list[str] = Field(default_factory=list)


class AIContextPackRequest(BaseModel):
    query: str = ""
    max_items: int = 6
    mode: Literal["balanced", "support-heavy", "opposition-heavy"] = "balanced"


class AIContextPackResponse(BaseModel):
    id: str
    query: str
    summary: str
    share_text: str
    safe_profile: SafeProfileResponse
    active_now: ActiveNowResponse
    topic_cards: list[TopicCard] = Field(default_factory=list)


class ChatWrapupMessage(BaseModel):
    role: str
    content: str


class ChatWrapupIn(BaseModel):
    source_app: str
    source_url: str | None = None
    conversation_title: str | None = None
    messages: list[ChatWrapupMessage] = Field(default_factory=list)
    user_note: str | None = None


class ChatWrapupResponse(BaseModel):
    id: str
    capture_id: str
    source_app: str
    conversation_title: str | None = None
    summary: str
    decisions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    inbox_path: str
    created_at: str
