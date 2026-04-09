import {
  DEFAULT_SERVER_URL,
  getSettings,
  saveSettings
} from "./shared.js";

const els = {
  serverUrl: document.querySelector("#serverUrl"),
  clientSecret: document.querySelector("#clientSecret"),
  saveButton: document.querySelector("#saveButton"),
  pingButton: document.querySelector("#pingButton"),
  status: document.querySelector("#status")
};

boot().catch((error) => {
  setStatus(error.message, true);
});

async function boot() {
  const settings = await getSettings();
  els.serverUrl.value = settings.serverUrl || DEFAULT_SERVER_URL;
  els.clientSecret.value = settings.clientSecret || "";

  els.saveButton.addEventListener("click", onSave);
  els.pingButton.addEventListener("click", onPing);
}

async function onSave() {
  await saveSettings({
    serverUrl: els.serverUrl.value,
    clientSecret: els.clientSecret.value
  });
  setStatus("Saved connection settings.");
}

async function onPing() {
  const serverUrl = els.serverUrl.value.trim() || DEFAULT_SERVER_URL;
  setStatus("Pinging local API…");
  try {
    const response = await fetch(`${serverUrl}/health`);
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    const payload = await response.json();
    setStatus(`Health check passed: ${payload.status} on ${payload.bind}.`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.style.color = isError ? "#b42318" : "";
}
