# AGENTS.md — Repo instructions for coding agents

These rules apply repo-wide unless a deeper `AGENTS.md` overrides them.

## Normativity (new vs existing)
- For **new code**: follow all **MUST** rules.
- For **existing code**: treat MUST rules as the target state; fix nearby violations
  opportunistically when you touch the area (SHOULD).

## Scope & intent (MIRROR-FIRST)
Primary rule: **mirror existing local patterns**.
- Write new code so it looks like it already belongs in this repo.
- Prefer the style, defaults, naming, error handling, and wiring used in the nearest
  file in the same area.

Non-goals:
- Do NOT “modernize,” “standardize,” or refactor unrelated code.
- Do NOT add abstraction layers, helpers, or cleanup for aesthetics alone.
- Avoid drive-by formatting or architecture changes unless the task actually needs them.

## MUST: User-controlled minimalism
If the user asks for the simplest possible or minimal solution, treat that as a hard
constraint.
- Prefer the fewest files, branches, abstractions, and moving parts needed for the
  requested behavior.
- Do NOT add future-proofing, generalization, or cleanup unless required by the
  current task or explicitly approved by the user.

## MUST: No unapproved expansion
If the user wants only the stated behavior:
- Do NOT add extra validation, alternate flows, comments, or support features unless
  they are required by the task.
- Surface design choices with non-obvious consequences before implementing them.

## MUST: Evidence discipline
When analyzing bugs, UX problems, capture failures, or regressions:
- Separate observed facts from inferences and hypotheses.
- Inspect the producing code path before generalizing from one symptom.
- If later evidence weakens a claim, retract it cleanly and rebuild from proven facts.
- Use direct language about what is proven, what is inferred, and what would verify
  the rest.

## MUST: Shared worktree awareness
If concurrent edits from the user or another process may exist:
- Inspect the current worktree before editing.
- Do NOT revert unrelated changes.
- Adapt around live edits unless they directly conflict with the task.

## MUST: Privacy and logging discipline
This repo handles clipboard content, captured selections, notes, and profile
inferences. Treat them as sensitive by default.
- MUST NOT commit secrets, local tokens, or client secrets.
- MUST NOT log full captured text, full clipboard contents, raw private notes, or
  authentication headers unless the task explicitly requires it.
- Prefer logs that include event type, timing, and high-level metadata rather than raw
  payload contents.

## MUST: Local-first security defaults
- The API MUST bind to loopback by default, not `0.0.0.0`.
- Extension or desktop clients MUST authenticate to the local API.
- Do NOT weaken origin checks, loopback checks, or secret requirements casually.

## MUST: Capture invariants
- Raw captures in `vault/raw/` are immutable source records. Do not silently rewrite or
  mutate them after capture.
- Inbox notes and profile suggestions are derived artifacts and may be regenerated.
- Public-source snapshots and private-source selection-only capture are product
  behavior, not implementation accidents. Preserve that distinction unless the user
  asks to change it.

## MUST: Interface stability
The following behave like local public APIs:
- FastAPI routes in `mousekb/api.py`
- request/response models in `mousekb/models.py`
- extension-to-backend request shapes
- CLI commands documented in `README.md`

Rules:
- MUST NOT rename routes, fields, or CLI commands casually.
- If one of those surfaces changes, update all in-repo callers in the same change:
  Python tests, extension code, CLI/docs, and any related storage assumptions.

## MUST: Use the project-local virtual environment
- Prefer `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/mousekb`, and `uv sync`
  in this repo.
- Do NOT assume global Python packages are present.
- When adding dependencies, keep them in `pyproject.toml` and refresh `uv.lock`.

## SHOULD: Reliability loop (Research → Implement → Verify)
New changes SHOULD follow a tight loop:
- Research: read the nearest existing files and confirm repo facts before editing.
- Implement: keep diffs single-theme.
- Verify: run the closest tests or smoke checks, then do a falsification pass.

If the same mistake repeats, prefer a small guardrail such as a focused test over
adding more prompt text.

## SHOULD: Prefer bounded work
Before shipping, check whether the change introduces:
- repeated full scans of large note collections or snapshots
- repeated embedding work for the same input
- N+1 DB or file-system reads
- unbounded buffering of large snapshots or transcripts

Optimize obviously hot or user-visible paths. Do NOT add speculative caching or
batching to cold paths.

## Router (Keep Context Small)
Read only the instructions relevant to the area you are changing:
- `mousekb/**`: backend, storage, indexing, CLI, quick-capture UI
- `extension/**`: Chrome extension capture UX, side panel, options
- `tests/**`: verification of API contracts and core storage behavior
- `README.md`: setup, run flow, operator-facing commands

If you are touching many areas at once, prefer a small, coordinated change rather than
mixing unrelated cleanup.

## Repo map (high signal)
- `mousekb/` — Python backend, storage, CLI, quick-capture UI
- `extension/` — Chrome MV3 extension
- `vault/` — local Markdown knowledge vault
- `data/` — local SQLite DB and client secret
- `tests/` — API and storage verification

## SHOULD: Verification
- Run the closest tests first, usually:
  - `.venv/bin/python -m pytest -q`
- For extension changes, do a syntax check when possible:
  - `node --check < extension/content.js`
  - `node --check --input-type=module < extension/service_worker.js`
- For CLI or server changes, prefer a local smoke command in `.venv`:
  - `.venv/bin/mousekb print-secret`
  - `.venv/bin/mousekb shortcut-status`
  - `.venv/bin/mousekb serve`
