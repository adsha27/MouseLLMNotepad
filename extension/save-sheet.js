import {
  apiFetch,
  clearDraft,
  getDraft,
  normalizeTags
} from "./shared.js";

const els = {
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  capturePolicy: document.querySelector("#capturePolicy"),
  selectedText: document.querySelector("#selectedText"),
  userNote: document.querySelector("#userNote"),
  tagsInput: document.querySelector("#tagsInput"),
  includeSnapshot: document.querySelector("#includeSnapshot"),
  saveButton: document.querySelector("#saveButton"),
  openPanelButton: document.querySelector("#openPanelButton"),
  openOptionsButton: document.querySelector("#openOptionsButton"),
  status: document.querySelector("#status")
};

let draft = null;

boot().catch((error) => {
  setStatus(error.message, true);
});

async function boot() {
  draft = await getDraft();
  if (!draft) {
    setStatus("No pending selection found. Select text in Chrome and try again.", true);
    els.saveButton.disabled = true;
    return;
  }

  els.pageTitle.textContent = draft.page_title || "Untitled page";
  els.pageUrl.textContent = draft.page_url || "";
  els.selectedText.value = draft.selected_text || "";
  els.includeSnapshot.checked = Boolean(draft.is_public_source && draft.page_snapshot_markdown);
  els.capturePolicy.textContent = draft.is_public_source
    ? "Public-looking page: snapshot is available."
    : "Private-looking source: selection-only by default.";

  els.saveButton.addEventListener("click", onSave);
  els.openPanelButton.addEventListener("click", onOpenPanel);
  els.openOptionsButton.addEventListener("click", () => chrome.runtime.openOptionsPage());
}

async function onSave() {
  if (!draft) {
    return;
  }

  els.saveButton.disabled = true;
  setStatus("Saving to your inbox…");
  try {
    const payload = {
      selected_text: draft.selected_text,
      page_url: draft.page_url,
      page_title: draft.page_title,
      page_snapshot_markdown: els.includeSnapshot.checked ? draft.page_snapshot_markdown : null,
      is_public_source: Boolean(draft.is_public_source),
      user_note: els.userNote.value.trim() || null,
      tags: normalizeTags(els.tagsInput.value)
    };

    const response = await apiFetch("/captures/browser", {
      method: "POST",
      body: payload
    });
    setStatus(`Saved ${response.id}. Closing…`);
    await chrome.runtime.sendMessage({ type: "clear-draft" });
    window.setTimeout(() => window.close(), 700);
  } catch (error) {
    setStatus(error.message, true);
    els.saveButton.disabled = false;
  }
}

async function onOpenPanel() {
  await chrome.runtime.sendMessage({ type: "open-side-panel" });
  window.close();
}

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.style.color = isError ? "#b42318" : "";
}
