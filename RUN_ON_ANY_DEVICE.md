# Run MouseLLMNotepad On Any Device

This guide is about getting MouseLLMNotepad running on a new machine without guessing what is supported.

## The Core Rule

MouseLLMNotepad is a same-machine app in this MVP:

- the FastAPI backend listens on `127.0.0.1:8765`
- the browser extension is allowed to talk only to `127.0.0.1:8765` or `localhost:8765`
- the browser and backend are expected to run on the same device

So "run it on any device" means: install and run it locally on that device.

## Choose The Right Setup

### 1. Linux desktop or laptop

Use this if you want the full experience: browser capture, side panel, and the optional quick-capture window.

1. Install the basics:

   ```bash
   sudo apt update
   sudo apt install -y git python3 python3-venv
   ```

   Then install `uv` if you do not already have it.

2. Clone the repo:

   ```bash
   git clone https://github.com/adsha27/MouseLLMNotepad.git
   cd MouseLLMNotepad
   ```

3. Create the local virtual environment and install Python dependencies:

   ```bash
   uv sync --extra dev
   ```

4. Start the backend:

   ```bash
   uv run mousekb serve
   ```

5. In another terminal, print the client secret:

   ```bash
   uv run mousekb print-secret
   ```

6. Load the extension:
   - Open `chrome://extensions`
   - Turn on `Developer mode`
   - Click `Load unpacked`
   - Pick the `extension/` directory from this repo

7. Open the extension options page and set:
   - `Server URL`: `http://127.0.0.1:8765`
   - `Client secret`: the value from `uv run mousekb print-secret`

8. Try the happy path:
   - open a normal public web page
   - select some text
   - click `Add to KB`
   - confirm the save sheet appears
   - open the side panel and search for the captured text

### Optional: Linux quick capture outside the browser

The quick-capture window is GTK-based and currently Linux-first.

1. Check whether your project Python can import `gi`:

   ```bash
   .venv/bin/python -c "import gi; print('gi ok')"
   ```

2. If that works, try:

   ```bash
   uv run mousekb quick-capture
   ```

3. If you are on GNOME and want a keyboard shortcut:

   ```bash
   uv run mousekb shortcut-status
   uv run mousekb bind-gnome-shortcut --binding '<Ctrl><Shift>K>'
   ```

If the `gi` import fails, the backend and browser extension are still usable. The quick-capture desktop window is just not available on that machine yet.

## 2. macOS desktop or laptop

Use this when you mainly want browser capture plus the side panel.

1. Install `git`, `Python 3.12+`, and `uv`.
2. Clone the repo:

   ```bash
   git clone https://github.com/adsha27/MouseLLMNotepad.git
   cd MouseLLMNotepad
   ```

3. Install dependencies:

   ```bash
   uv sync --extra dev
   ```

4. Start the backend:

   ```bash
   uv run mousekb serve
   ```

5. Print the secret:

   ```bash
   uv run mousekb print-secret
   ```

6. Load the unpacked extension from `extension/` into Chrome or another Chromium-based browser that supports MV3 side panels.
7. Save the server URL and secret in the extension options.
8. Use browser selection capture and the side panel normally.

Current limitation: the shipped quick-capture desktop window and GNOME shortcut helper are not part of the macOS path in this MVP.

## 3. Windows desktop or laptop

The Windows path is similar to macOS: browser capture works, but the Linux GTK quick-capture helper is not part of the supported path.

1. Install `git`, `Python 3.12+`, and `uv`.
2. Clone the repo:

   ```bash
   git clone https://github.com/adsha27/MouseLLMNotepad.git
   cd MouseLLMNotepad
   ```

3. Install dependencies:

   ```bash
   uv sync --extra dev
   ```

4. Start the backend:

   ```bash
   uv run mousekb serve
   ```

5. Print the secret:

   ```bash
   uv run mousekb print-secret
   ```

6. Load `extension/` as an unpacked extension in Chrome or Edge.
7. Save the server URL and secret in the extension options.
8. Test capture on a normal web page.

## 4. Moving an existing setup to another device

If you already have data on one machine and want the same vault on another:

1. Copy the repo, including:
   - `vault/`
   - `data/`

2. On the new device, run:

   ```bash
   uv sync --extra dev
   uv run mousekb serve
   ```

3. If you copied `data/client_secret.txt`, your old secret will continue to work.
4. If you did not copy `data/`, run:

   ```bash
   uv run mousekb reindex
   uv run mousekb print-secret
   ```

5. Update the extension options on the new device with the new secret if needed.

### What gets preserved

- `vault/raw/`: your raw Markdown captures and snapshots
- `vault/inbox/`: review notes created for captures
- `data/app.db`: search index, profile suggestions, context-pack history, approvals
- `data/client_secret.txt`: local API secret

### What `reindex` does

`uv run mousekb reindex` rebuilds the capture index from Markdown in `vault/raw/`.

It is useful when:

- you copied raw captures without the SQLite database
- you intentionally want to rebuild the search index
- `data/app.db` was removed or corrupted

It is not a full machine-clone command. If you want the closest possible copy of your original setup, bring `data/` with you too.

## 5. What Is Not Supported Today

- iPhone, iPad, and Android are not first-class targets for this MVP.
- Firefox and Safari are not first-class targets for the bundled extension.
- Running the browser on one machine and the backend on another is not the default setup.
- Cloud sync is not included.

## 6. Common Problems

### The extension says it cannot connect

Check all of these:

- `uv run mousekb serve` is still running
- the extension points to `http://127.0.0.1:8765`
- the saved secret matches `uv run mousekb print-secret`
- you reloaded the browser tab after loading the extension

### Search works, but the chip never appears

- Make sure you are on a normal page where text selection is possible.
- Reload the current tab after installing or reloading the extension.
- Confirm the extension is enabled for that browser profile.

### `quick-capture` fails on Linux

If you see `ModuleNotFoundError: No module named 'gi'`, your Python environment does not currently have the GTK / PyGObject bridge available. The browser-based workflow is still supported on that machine.

### I want to use a different port

The backend can be configured, but the extension manifest currently grants access only to `127.0.0.1:8765` and `localhost:8765`.

If you change the port, you also need to:

1. update `extension/manifest.json`
2. reload the unpacked extension
3. update the server URL in extension options

## 7. Recommended Default

If you are choosing only one path today, use this one:

- run the backend locally
- use Chrome or another Chromium-based browser
- use the extension for capture
- treat Linux desktop quick capture as a bonus, not a requirement

That is the most stable way to run MouseLLMNotepad across machines right now.
