import { apiFetch, clearDraft, getLastCapture, saveDraft, saveLastCapture } from "./shared.js";

chrome.runtime.onInstalled.addListener(async () => {
  try {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  } catch (_error) {
    // Side panel behavior is best-effort; some Chrome builds may handle action clicks differently.
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "open-save-sheet") {
    handleOpenSaveSheet(message.draft)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "open-side-panel") {
    handleOpenSidePanel(sender)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "save-browser-capture") {
    handleSaveBrowserCapture(message.draft)
      .then((capture) => sendResponse({ ok: true, capture }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "open-review-sheet") {
    handleOpenReviewSheet(message.captureId)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "mark-capture-private") {
    handleMarkCapturePrivate(message.captureId)
      .then((capture) => sendResponse({ ok: true, capture }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "save-chat-wrapup") {
    handleSaveChatWrapup(message.payload)
      .then((wrapup) => sendResponse({ ok: true, wrapup }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "clear-draft") {
    clearDraft()
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  return false;
});

async function handleOpenSaveSheet(draft) {
  await saveDraft(draft);
  await chrome.windows.create({
    url: chrome.runtime.getURL("save-sheet.html"),
    type: "popup",
    width: 540,
    height: 760
  });
}

async function handleSaveBrowserCapture(draft) {
  const capture = await apiFetch("/captures/browser", {
    method: "POST",
    body: {
      selected_text: draft.selected_text,
      page_url: draft.page_url,
      page_title: draft.page_title,
      page_snapshot_markdown: draft.is_public_source ? draft.page_snapshot_markdown : null,
      is_public_source: Boolean(draft.is_public_source),
      user_note: null,
      tags: []
    }
  });
  await saveLastCapture(capture);
  return capture;
}

async function handleOpenReviewSheet(captureId) {
  const lastCapture = await getLastCapture();
  if (!lastCapture || (captureId && lastCapture.id !== captureId)) {
    throw new Error("No recent capture is ready for review.");
  }
  await chrome.windows.create({
    url: chrome.runtime.getURL(`save-sheet.html?mode=review&captureId=${encodeURIComponent(lastCapture.id)}`),
    type: "popup",
    width: 540,
    height: 760
  });
}

async function handleOpenSidePanel(sender) {
  if (sender?.tab?.windowId) {
    await chrome.sidePanel.open({ windowId: sender.tab.windowId });
    return;
  }
  const [currentWindow] = await chrome.windows.getAll({ populate: false, windowTypes: ["normal"] });
  if (currentWindow?.id) {
    await chrome.sidePanel.open({ windowId: currentWindow.id });
  }
}

async function handleMarkCapturePrivate(captureId) {
  if (!captureId) {
    throw new Error("No capture selected.");
  }
  const capture = await apiFetch(`/captures/${encodeURIComponent(captureId)}/mark-private`, {
    method: "POST"
  });
  await saveLastCapture(capture);
  return capture;
}

async function handleSaveChatWrapup(payload) {
  const wrapup = await apiFetch("/ai/chat-wrapups", {
    method: "POST",
    body: payload
  });
  return wrapup;
}
