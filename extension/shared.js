export const DEFAULT_SERVER_URL = "http://127.0.0.1:8765";
export const SETTINGS_KEYS = {
  serverUrl: "serverUrl",
  clientSecret: "clientSecret"
};
export const DRAFT_KEY = "draftCapture";
export const LAST_CAPTURE_KEY = "lastCapture";

export async function getSettings() {
  const stored = await chrome.storage.local.get({
    [SETTINGS_KEYS.serverUrl]: DEFAULT_SERVER_URL,
    [SETTINGS_KEYS.clientSecret]: ""
  });
  return {
    serverUrl: stored[SETTINGS_KEYS.serverUrl] || DEFAULT_SERVER_URL,
    clientSecret: stored[SETTINGS_KEYS.clientSecret] || ""
  };
}

export async function saveSettings({ serverUrl, clientSecret }) {
  await chrome.storage.local.set({
    [SETTINGS_KEYS.serverUrl]: serverUrl.trim() || DEFAULT_SERVER_URL,
    [SETTINGS_KEYS.clientSecret]: clientSecret.trim()
  });
}

export async function getDraft() {
  const stored = await chrome.storage.session.get({ [DRAFT_KEY]: null });
  return stored[DRAFT_KEY];
}

export async function saveDraft(draft) {
  await chrome.storage.session.set({ [DRAFT_KEY]: draft });
}

export async function clearDraft() {
  await chrome.storage.session.remove(DRAFT_KEY);
}

export async function getLastCapture() {
  const stored = await chrome.storage.session.get({ [LAST_CAPTURE_KEY]: null });
  return stored[LAST_CAPTURE_KEY];
}

export async function saveLastCapture(capture) {
  await chrome.storage.session.set({ [LAST_CAPTURE_KEY]: capture });
}

export function normalizeTags(rawValue) {
  return rawValue
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean)
    .filter((value, index, all) => all.indexOf(value) === index);
}

export function prettyDate(value) {
  if (!value) {
    return "";
  }
  try {
    return new Date(value).toLocaleString();
  } catch (_error) {
    return value;
  }
}

export function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export async function apiFetch(path, { method = "GET", body = null } = {}) {
  const settings = await getSettings();
  if (!settings.clientSecret) {
    throw new Error("Open MouseKB options and save your local client secret first.");
  }

  const response = await fetch(`${settings.serverUrl}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-MouseKB-Client-Secret": settings.clientSecret
    },
    body: body ? JSON.stringify(body) : undefined
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_error) {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}
