# MouseLLMNotepad

MouseLLMNotepad is a local-first personal knowledge capture tool for saving the text you highlight, the notes you keep, and the patterns in how you think.

Inside the codebase, the Python package and browser extension are still named `mousekb` / `MouseKB`. The repo name is `MouseLLMNotepad`.

## What It Does

- Saves selected text from a Chromium-based browser through a floating `Add to KB` chip.
- Stores raw captures as Markdown in `vault/raw/` so your source material stays readable.
- Indexes captures in `data/app.db` for local search, profile suggestions, and context-pack generation.
- Keeps all capture traffic on the same machine by binding the API to `127.0.0.1`.
- Offers a Linux-first quick-capture window for copied text outside the browser.

## Platform Support

| Device / OS | Browser capture | Side panel | Desktop quick capture | Notes |
| --- | --- | --- | --- | --- |
| Linux desktop or laptop | Yes | Yes | Yes, if GTK/PyGObject is available | Best-supported setup today |
| macOS desktop or laptop | Yes | Yes | Not shipped in this MVP | Use browser capture only |
| Windows desktop or laptop | Yes | Yes | Not shipped in this MVP | Use browser capture only |
| Phones / tablets | No | No | No | Unpacked desktop extensions and local loopback service are not supported there |

Important: this MVP is designed to run locally on each machine. The browser extension expects a backend on `http://127.0.0.1:8765` or `http://localhost:8765`, so the browser and API should live on the same device.

## Quick Start

1. Install `Python 3.12+`, `git`, and [`uv`](https://docs.astral.sh/uv/).
2. Clone the repo and enter it:

   ```bash
   git clone https://github.com/adsha27/MouseLLMNotepad.git
   cd MouseLLMNotepad
   ```

3. Create the project-local virtual environment and install dependencies:

   ```bash
   uv sync --extra dev
   ```

   This creates and uses `.venv` for the project.

4. Start the local API:

   ```bash
   uv run mousekb serve
   ```

5. In a second terminal, print the local client secret:

   ```bash
   uv run mousekb print-secret
   ```

6. Load the unpacked extension from `extension/` in Chrome, Chromium, Brave, or Edge:
   - Open `chrome://extensions`
   - Turn on `Developer mode`
   - Click `Load unpacked`
   - Select the repo's `extension/` folder

7. Open the extension options page and save:
   - `Server URL`: `http://127.0.0.1:8765`
   - `Client secret`: the output from `uv run mousekb print-secret`

8. Highlight text on a web page. You should see the `Add to KB` chip appear near the selection.

For the full platform-by-platform guide, see [RUN_ON_ANY_DEVICE.md](/home/aditya/not_work/mouseLLMnotepad/RUN_ON_ANY_DEVICE.md).

## How MouseLLMNotepad Is Organized

```text
mousekb/         FastAPI app, storage layer, search, profile logic, CLI, quick capture
extension/       Chrome MV3 extension
vault/raw/       Immutable raw captures and snapshots
vault/inbox/     Reviewable inbox notes with suggestions
vault/profile/   Approved and pending profile summaries
data/app.db      SQLite index and profile state
data/client_secret.txt  Local client secret generated on first run
```

## Commands

- `uv run mousekb serve`
- `uv run mousekb serve --reload`
- `uv run mousekb print-secret`
- `uv run mousekb reindex`
- `uv run mousekb quick-capture`
- `uv run mousekb shortcut-status`
- `uv run mousekb bind-gnome-shortcut --binding '<Ctrl><Shift>K>'`

## Moving To Another Device

The simplest way to move your data is to copy the repo with both `vault/` and `data/`.

- Copy `vault/` if you want the raw Markdown captures.
- Copy `data/` if you want the SQLite index, profile approvals, pending suggestions, and existing client secret.
- If you copy only `vault/`, run `uv run mousekb reindex` on the new machine to rebuild the capture index.

If the new machine generates a new `data/client_secret.txt`, update the extension's saved secret on that machine.

## Local-First Security Defaults

- The backend binds to `127.0.0.1` by default.
- All non-health endpoints require the `X-MouseKB-Client-Secret` header.
- The extension only has host permissions for `http://127.0.0.1:8765/*` and `http://localhost:8765/*`.

That means this repo is set up for same-machine use by default, not for exposing your knowledge base over the network.

## Troubleshooting

- If the extension cannot save, make sure `uv run mousekb serve` is running and the secret in the options page matches `uv run mousekb print-secret`.
- If the `Add to KB` chip does not appear, reload the tab after loading or reloading the extension.
- If `uv run mousekb quick-capture` fails with `No module named 'gi'`, your Python environment does not currently have GTK / PyGObject available. Browser capture will still work.
- If you change the API host or port, you will also need to update `extension/manifest.json` host permissions and reload the unpacked extension.

## Current MVP Boundaries

- No cloud sync
- No background external model calls
- No mobile app
- No first-class Firefox or Safari support
- No cross-device shared server mode out of the box

This version is meant to be a strong local-first foundation you can run on a laptop or desktop and later extend.
