from __future__ import annotations

import re
from collections import Counter


TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9\-\+_/\.]{1,}")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "what",
    "when",
    "with",
    "you",
    "your",
}

PRIVATE_HOST_PATTERNS = (
    "localhost",
    "127.0.0.1",
    "mail.",
    "chat.",
    "claude.ai",
    "chatgpt.com",
    "openai.com",
    "slack.com",
    "discord.com",
    "web.whatsapp.com",
    "notion.so",
    "docs.google.com",
)

CONTRARIAN_CUES = (
    "anti",
    "against",
    "counterargument",
    "counter-argument",
    "critique",
    "skeptic",
    "skeptical",
    "opposing",
    "opposition",
    "objection",
    "debunk",
    "rebuttal",
    "devil's advocate",
    "steelman",
)

FIRST_PRINCIPLES_CUES = (
    "first principles",
    "fundamental",
    "base assumptions",
    "from scratch",
)

EVIDENCE_CUES = (
    "proof",
    "evidence",
    "citation",
    "citations",
    "study",
    "studies",
    "experiment",
    "data",
    "source",
    "sources",
)

KNOWLEDGE_CUES = (
    "already know",
    "skip the basics",
    "advanced",
    "technical detail",
    "deep dive",
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def extract_keyphrases(text: str, *, limit: int = 6) -> list[str]:
    tokens = [token for token in tokenize(text) if token not in STOPWORDS and len(token) > 2]
    counts: Counter[str] = Counter(tokens)

    for left, right in zip(tokens, tokens[1:]):
        if left == right:
            continue
        phrase = f"{left} {right}"
        if left in STOPWORDS or right in STOPWORDS:
            continue
        counts[phrase] += 2

    selected: list[str] = []
    for phrase, _ in counts.most_common(limit * 4):
        if any(phrase in existing or existing in phrase for existing in selected):
            continue
        selected.append(phrase)
        if len(selected) == limit:
            break
    return selected


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def classify_sensitivity(
    *,
    source_type: str,
    page_url: str | None = None,
    is_public_source: bool | None = None,
    sensitivity_override: str | None = None,
) -> str:
    if sensitivity_override in {"public", "private", "sensitive"}:
        return sensitivity_override

    if source_type == "clipboard":
        return "private"

    if is_public_source is False:
        return "private"

    normalized = normalize_text(page_url or "")
    if any(pattern in normalized for pattern in PRIVATE_HOST_PATTERNS):
        return "private"

    return "public"


def detect_reasoning_cues(text: str) -> dict[str, bool]:
    lowered = normalize_text(text)
    return {
        "contrarian_interest": any(cue in lowered for cue in CONTRARIAN_CUES),
        "first_principles": any(cue in lowered for cue in FIRST_PRINCIPLES_CUES),
        "evidence_preference": any(cue in lowered for cue in EVIDENCE_CUES),
        "knowledge_level": any(cue in lowered for cue in KNOWLEDGE_CUES),
    }


def infer_stance(text: str, *, stance_override: str | None = None) -> str:
    if stance_override in {"neutral", "opposing", "supporting"}:
        return stance_override
    cues = detect_reasoning_cues(text)
    if cues["contrarian_interest"]:
        return "opposing"
    return "neutral"


def snippet_for_query(text: str, query: str, *, width: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    lowered = compact.lower()
    lowered_query = query.lower().strip()
    if not lowered_query:
        return compact[:width]
    index = lowered.find(lowered_query)
    if index == -1:
        return compact[:width]
    start = max(0, index - width // 3)
    end = min(len(compact), start + width)
    prefix = "..." if start else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"
