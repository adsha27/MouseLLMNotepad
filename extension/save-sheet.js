import {
  apiFetch,
  getDraft,
  getLastCapture,
  normalizeTags,
  saveLastCapture
} from "./shared.js";

const els = {
  eyebrow: document.querySelector("#eyebrow"),
  heroTitle: document.querySelector("#heroTitle"),
  heroCopy: document.querySelector("#heroCopy"),
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  capturePolicy: document.querySelector("#capturePolicy"),
  selectedTextLabel: document.querySelector("#selectedTextLabel"),
  selectedText: document.querySelector("#selectedText"),
  userNoteLabel: document.querySelector("#userNoteLabel"),
  userNote: document.querySelector("#userNote"),
  tagsLabel: document.querySelector("#tagsLabel"),
  tagsInput: document.querySelector("#tagsInput"),
  stanceRow: document.querySelector("#stanceRow"),
  stanceSelect: document.querySelector("#stanceSelect"),
  snapshotRow: document.querySelector("#snapshotRow"),
  includeSnapshot: document.querySelector("#includeSnapshot"),
  saveButton: document.querySelector("#saveButton"),
  openPanelButton: document.querySelector("#openPanelButton"),
  openOptionsButton: document.querySelector("#openOptionsButton"),
  status: document.querySelector("#status")
};

const params = new URLSearchParams(window.location.search);
const mode = params.get("mode") === "review" ? "review" : "capture";
const requestedCaptureId = params.get("captureId");

let draft = null;
let capture = null;

boot().catch((error) => {
  setStatus(error.message, true);
});

async function boot() {
  els.openPanelButton.addEventListener("click", onOpenPanel);
  els.openOptionsButton.addEventListener("click", () => chrome.runtime.openOptionsPage());

  if (mode === "review") {
    await bootReviewMode();
    return;
  }

  await bootCaptureMode();
}

async function bootCaptureMode() {
  draft = await getDraft();
  if (!draft) {
    setStatus("No pending selection found. Select text in Chrome and try again.", true);
    els.saveButton.disabled = true;
    return;
  }

  els.eyebrow.textContent = "Quick Capture";
  els.heroTitle.textContent = "Save this selection before it slips.";
  els.heroCopy.textContent = "Everything lands in your inbox first. Suggested tags and profile clues stay reviewable.";
  els.selectedTextLabel.textContent = "Selected text";
  els.userNoteLabel.textContent = "Quick note";
  els.tagsLabel.textContent = "Tags";
  els.userNote.placeholder = "Why are you keeping this? What does it connect to?";
  els.saveButton.textContent = "Save to Inbox";
  els.stanceRow.hidden = true;
  els.snapshotRow.hidden = false;

  els.pageTitle.textContent = draft.page_title || "Untitled page";
  els.pageUrl.textContent = draft.page_url || "";
  els.selectedText.value = draft.selected_text || "";
  els.includeSnapshot.checked = Boolean(draft.is_public_source && draft.page_snapshot_markdown);
  els.capturePolicy.textContent = draft.is_public_source
    ? "Public-looking page: snapshot is available."
    : "Private-looking source: selection-only by default.";

  els.saveButton.addEventListener("click", onSaveCapture);
}

async function bootReviewMode() {
  capture = await getLastCapture();
  if (!capture || (requestedCaptureId && capture.id !== requestedCaptureId)) {
    setStatus("No recent capture is ready for review yet. Save something first, then try again.", true);
    els.saveButton.disabled = true;
    els.snapshotRow.hidden = true;
    return;
  }

  els.eyebrow.textContent = "Review";
  els.heroTitle.textContent = "Add context after the fast save.";
  els.heroCopy.textContent = "The capture is already stored. This sheet only updates your review note and review tags.";
  els.selectedTextLabel.textContent = "Captured text";
  els.userNoteLabel.textContent = "Review note";
  els.tagsLabel.textContent = "Review tags";
  els.userNote.placeholder = "Why does this matter? What should future AI chats understand from it?";
  els.saveButton.textContent = "Save Review";
  els.stanceRow.hidden = false;
  els.snapshotRow.hidden = true;

  els.pageTitle.textContent = capture.page_title || capture.source_app || capture.id;
  els.pageUrl.textContent = capture.page_url || capture.source_app || "Local capture";
  els.selectedText.value = capture.selected_text || "";
  els.userNote.value = capture.review_note || "";
  els.tagsInput.value = (capture.review_tags || []).join(", ");
  els.stanceSelect.value = capture.stance || "neutral";
  els.capturePolicy.textContent = capture.sensitivity === "sensitive"
    ? "Sensitive capture: this stays out of the AI-facing memory layer unless you explicitly share it."
    : "Review updates stay local-first and feed lightweight background organization.";

  els.saveButton.addEventListener("click", onSaveReview);
}

async function onSaveCapture() {
  if (!draft) {
    return;
  }

  els.saveButton.disabled = true;
  setStatus("Saving to your inbox…");
  try {
    const response = await apiFetch("/captures/browser", {
      method: "POST",
      body: {
        selected_text: draft.selected_text,
        page_url: draft.page_url,
        page_title: draft.page_title,
        page_snapshot_markdown: els.includeSnapshot.checked ? draft.page_snapshot_markdown : null,
        is_public_source: Boolean(draft.is_public_source),
        user_note: els.userNote.value.trim() || null,
        tags: normalizeTags(els.tagsInput.value)
      }
    });
    await saveLastCapture(response);
    setStatus(`Saved ${response.id}. Closing…`);
    await chrome.runtime.sendMessage({ type: "clear-draft" });
    window.setTimeout(() => window.close(), 700);
  } catch (error) {
    setStatus(error.message, true);
    els.saveButton.disabled = false;
  }
}

async function onSaveReview() {
  if (!capture) {
    return;
  }

  els.saveButton.disabled = true;
  setStatus("Saving your review note…");
  try {
    const response = await apiFetch(`/captures/${encodeURIComponent(capture.id)}/review`, {
      method: "POST",
      body: {
        review_note: els.userNote.value.trim() || null,
        review_tags: normalizeTags(els.tagsInput.value),
        stance_override: els.stanceSelect.value || "neutral"
      }
    });
    capture = response;
    await saveLastCapture(response);
    setStatus(`Updated ${response.id}. Closing…`);
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
