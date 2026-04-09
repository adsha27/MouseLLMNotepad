# MouseKB

MouseKB is a local-first personal knowledge capture tool built around two entry points:

- Chrome selection capture with a floating `Add to KB` chip, a compact save sheet, and a side panel for search/profile/context packs.
- Desktop quick capture for copied text outside the browser.

The backend stores immutable raw captures as Markdown under `vault/raw/` and keeps a SQLite index in `data/app.db` for hybrid search, profile suggestions, and context-pack generation.

## What Ships In This MVP

- FastAPI backend bound to `127.0.0.1`
- Local secret authentication for extension and quick-capture clients
- Browser capture policy with public-page snapshots and private-source selection-only mode
- Inbox-first note organization with tag/topic/folder suggestions
- Hybrid retrieval using SQLite FTS plus lightweight hashed embeddings
- Reviewable profile suggestions for domain, knowledge level, evidence preference, reasoning style, recurring topics, and contrarian interests
- Context-pack export for use with frontier models
- GTK 4 quick-capture window for copied text outside the browser
- Chrome MV3 extension with content script, save sheet, side panel, and options page

## Project Layout

```text
mousekb/         Python backend, storage, search, quick-capture UI, CLI helpers
extension/       Chrome MV3 extension
vault/raw/       Immutable raw captures and snapshots
vault/inbox/     Reviewable inbox notes with suggestions
vault/profile/   Approved and pending profile summaries
data/app.db      SQLite index
```

## Getting Started

1. Create the environment and install dependencies:

   ```bash
   uv sync --extra dev
   ```

2. Start the local API:

   ```bash
   uv run mousekb serve --reload
   ```

3. Print the client secret and keep it handy for the extension and quick-capture UI:

   ```bash
   uv run mousekb print-secret
   ```

4. Load the unpacked extension from `extension/` in Chrome.

5. Open the extension options page and save:

   - `Server URL`: `http://127.0.0.1:8765`
   - `Client Secret`: output from `mousekb print-secret`

6. Configure a desktop shortcut to run quick capture:

   ```bash
   uv run mousekb shortcut-status
   uv run mousekb bind-gnome-shortcut --binding '<Ctrl><Shift>K>'
   ```

   If GNOME shortcut registration is not what you want, bind your own OS shortcut to:

   ```bash
   uv run mousekb quick-capture
   ```

## Backend Commands

- `uv run mousekb serve --reload`
- `uv run mousekb print-secret`
- `uv run mousekb reindex`
- `uv run mousekb quick-capture`
- `uv run mousekb shortcut-status`
- `uv run mousekb bind-gnome-shortcut --binding '<Ctrl><Shift>K>'`

## Notes On Local Intelligence

This MVP intentionally avoids an always-on local generative model. Instead it uses:

- SQLite FTS for exact and phrase search
- Hashed local embeddings for semantic similarity
- Lightweight heuristics for sensitivity, profile-suggestion generation, contrarian detection, and tag/topic extraction

That keeps the capture path cheap and reliable while preserving a clean seam for later local-LLM enrichment or an MCP adapter.
