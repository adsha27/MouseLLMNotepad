from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


FRONTMATTER_BOUNDARY = "---"


def slugify(value: str, *, fallback: str = "capture") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized[:80] or fallback


def dump_frontmatter(meta: dict[str, Any]) -> str:
    lines = [FRONTMATTER_BOUNDARY]
    for key, value in meta.items():
        if isinstance(value, (list, dict, bool)) or value is None:
            encoded = json.dumps(value, sort_keys=True)
        else:
            encoded = str(value)
        lines.append(f"{key}: {encoded}")
    lines.append(FRONTMATTER_BOUNDARY)
    return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith(FRONTMATTER_BOUNDARY):
        return {}, text

    parts = text.split(FRONTMATTER_BOUNDARY, 2)
    if len(parts) < 3:
        return {}, text

    _, raw_meta, body = parts
    meta: dict[str, Any] = {}
    for line in raw_meta.strip().splitlines():
        if ": " not in line:
            continue
        key, raw_value = line.split(": ", 1)
        raw_value = raw_value.strip()
        try:
            meta[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            meta[key] = raw_value
    return meta, body.lstrip("\n")


def build_capture_markdown(meta: dict[str, Any], *, selected_text: str, user_note: str | None) -> str:
    sections = [dump_frontmatter(meta), "", "## Selected Text", "", selected_text.strip(), ""]
    if user_note:
        sections.extend(["## User Note", "", user_note.strip(), ""])
    return "\n".join(sections).rstrip() + "\n"


def parse_capture_markdown(text: str) -> dict[str, Any]:
    meta, body = parse_frontmatter(text)
    selected_text = _extract_section(body, "Selected Text")
    user_note = _extract_section(body, "User Note")
    return {
        "meta": meta,
        "selected_text": selected_text.strip(),
        "user_note": user_note.strip() or None,
    }


def build_snapshot_markdown(*, title: str, source_url: str, body_markdown: str) -> str:
    return "\n".join(
        [
            f"# {title.strip() or 'Snapshot'}",
            "",
            f"Source: {source_url.strip()}",
            "",
            body_markdown.strip(),
            "",
        ]
    )


def relative_path(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _extract_section(body: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\n(?P<content>.*?)(?=^## |\Z)"
    match = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    return match.group("content").strip("\n")
