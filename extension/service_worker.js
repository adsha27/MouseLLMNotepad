import { clearDraft, saveDraft } from "./shared.js";

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
