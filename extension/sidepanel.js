import {
  apiFetch,
  escapeHtml,
  getLastCapture,
  prettyDate
} from "./shared.js";

const els = {
  openOptionsButton: document.querySelector("#openOptionsButton"),
  copySafeIntroButton: document.querySelector("#copySafeIntroButton"),
  copyCurrentContextButton: document.querySelector("#copyCurrentContextButton"),
  openChatGPTButton: document.querySelector("#openChatGPTButton"),
  safeProfileSummary: document.querySelector("#safeProfileSummary"),
  activeNowSummary: document.querySelector("#activeNowSummary"),
  sharePolicies: document.querySelector("#sharePolicies"),
  lastCapture: document.querySelector("#lastCapture"),
  lastCaptureStage: document.querySelector("#lastCaptureStage"),
  reviewLastCaptureButton: document.querySelector("#reviewLastCaptureButton"),
  markLastPrivateButton: document.querySelector("#markLastPrivateButton"),
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  searchStatus: document.querySelector("#searchStatus"),
  resultCount: document.querySelector("#resultCount"),
  results: document.querySelector("#results"),
  topicCardCount: document.querySelector("#topicCardCount"),
  topicCards: document.querySelector("#topicCards"),
  approvedProfile: document.querySelector("#approvedProfile"),
  pendingProfile: document.querySelector("#pendingProfile")
};

let safeProfile = null;
let activeNow = null;
let sharePolicies = null;
let lastCapture = null;

boot().catch((error) => {
  setSearchStatus(error.message, true);
});

async function boot() {
  els.openOptionsButton.addEventListener("click", () => chrome.runtime.openOptionsPage());
  els.copySafeIntroButton.addEventListener("click", onCopySafeIntro);
  els.copyCurrentContextButton.addEventListener("click", onCopyCurrentContext);
  els.openChatGPTButton.addEventListener("click", onOpenChatGPT);
  els.reviewLastCaptureButton.addEventListener("click", onReviewLastCapture);
  els.markLastPrivateButton.addEventListener("click", onMarkLastPrivate);
  els.searchForm.addEventListener("submit", onSearch);
  await Promise.all([refreshAiState(), refreshProfile()]);
}

async function onSearch(event) {
  event.preventDefault();
  const query = els.searchInput.value.trim();
  if (!query) {
    setSearchStatus("Enter a query first.");
    return;
  }

  setSearchStatus("Searching…");
  try {
    const response = await apiFetch(`/search?q=${encodeURIComponent(query)}`);
    renderResults(response.items);
    await refreshTopicCards(query);
    setSearchStatus(`Loaded ${response.total} results.`);
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

async function onCopySafeIntro() {
  if (!safeProfile) {
    await refreshAiState();
  }
  const text = safeProfile?.share_text?.trim() || safeProfile?.summary?.trim();
  if (!text) {
    setSearchStatus("MouseKB has not built a safe intro yet.");
    return;
  }
  await navigator.clipboard.writeText(text);
  setSearchStatus("Safe intro copied. Paste it into a plain ChatGPT or Codex chat.");
}

async function onCopyCurrentContext() {
  const query = els.searchInput.value.trim();
  setSearchStatus("Building a sanitized AI context…");
  try {
    const response = await apiFetch("/ai/context-packs", {
      method: "POST",
      body: {
        query,
        max_items: 6,
        mode: "balanced"
      }
    });
    await navigator.clipboard.writeText(response.share_text);
    setSearchStatus("Current context copied. Paste it into your chat before asking the next question.");
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

function onOpenChatGPT() {
  window.open("https://chatgpt.com/", "_blank", "noopener,noreferrer");
  setSearchStatus("Opened ChatGPT in a new tab. Paste the safe intro or current context there.");
}

async function onReviewLastCapture() {
  if (!lastCapture?.id) {
    setSearchStatus("No recent capture is ready for review.");
    return;
  }
  const response = await chrome.runtime.sendMessage({ type: "open-review-sheet", captureId: lastCapture.id });
  if (!response?.ok) {
    setSearchStatus(response?.error || "Could not open the review sheet.", true);
  }
}

async function onMarkLastPrivate() {
  if (!lastCapture?.id) {
    setSearchStatus("No recent capture is ready to mark private.");
    return;
  }
  const response = await chrome.runtime.sendMessage({
    type: "mark-capture-private",
    captureId: lastCapture.id
  });
  if (!response?.ok) {
    setSearchStatus(response?.error || "Could not update that capture.", true);
    return;
  }
  lastCapture = response.capture;
  renderLastCapture(lastCapture);
  setSearchStatus(`Marked ${lastCapture.id} private.`);
  await refreshAiState();
}

function renderResults(items) {
  els.resultCount.textContent = String(items.length);
  if (!items.length) {
    els.results.innerHTML = "<p class='status'>No results yet.</p>";
    return;
  }

  els.results.innerHTML = items
    .map(
      (item) => `
        <article class="result">
          <div class="result-head">
            <div>
              <h3>${escapeHtml(item.title)}</h3>
              <p class="result-meta">${escapeHtml(item.source_label)} · ${escapeHtml(prettyDate(item.created_at))}</p>
            </div>
          </div>
          <p class="snippet">${escapeHtml(item.snippet)}</p>
          <div class="chips">
            <span class="chip ${item.stance === "opposing" ? "warning-chip" : ""}">${escapeHtml(item.stance)}</span>
            ${(item.reasons || []).map((reason) => `<span class="chip">${escapeHtml(reason)}</span>`).join("")}
            ${(item.suggested_tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}
          </div>
        </article>
      `
    )
    .join("");
}

async function refreshAiState() {
  const [nextSafeProfile, nextActiveNow, nextSharePolicies, nextLastCapture] = await Promise.all([
    apiFetch("/ai/safe-profile"),
    apiFetch("/ai/active-now"),
    apiFetch("/ai/share-policies"),
    getLastCapture()
  ]);
  safeProfile = nextSafeProfile;
  activeNow = nextActiveNow;
  sharePolicies = nextSharePolicies;
  lastCapture = nextLastCapture;
  renderAiSummaries();
  renderSharePolicies();
  renderLastCapture(lastCapture);
  await refreshTopicCards(els.searchInput.value.trim());
}

async function refreshTopicCards(query = "") {
  try {
    const response = await apiFetch(`/ai/topic-cards?q=${encodeURIComponent(query)}`);
    renderTopicCards(response.items);
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

function renderAiSummaries() {
  els.safeProfileSummary.textContent = safeProfile?.summary || "MouseKB is still building your safe profile.";
  els.activeNowSummary.textContent = activeNow?.summary || "Recent captures will roll up here after the fast-save path.";
}

function renderSharePolicies() {
  const blocks = [];
  for (const rule of sharePolicies?.rules || []) {
    blocks.push(`<div class="rule-chip">${escapeHtml(rule)}</div>`);
  }
  for (const rule of sharePolicies?.explicit_share_required || []) {
    blocks.push(`<div class="rule-chip warning">${escapeHtml(`Explicit share required: ${rule}`)}</div>`);
  }
  els.sharePolicies.innerHTML = blocks.join("") || "<p class='status'>No sharing policy hints yet.</p>";
}

function renderLastCapture(capture) {
  if (!capture) {
    els.lastCaptureStage.textContent = "none";
    els.lastCapture.innerHTML = "<p class='status'>Your next capture will appear here so you can add a note without slowing down the save.</p>";
    els.reviewLastCaptureButton.disabled = true;
    els.markLastPrivateButton.disabled = true;
    return;
  }

  els.lastCaptureStage.textContent = capture.processing_stage || "saved";
  els.lastCapture.innerHTML = `
    <article class="result">
      <div class="result-head">
        <div>
          <h3>${escapeHtml(capture.page_title || capture.source_app || capture.id)}</h3>
          <p class="result-meta">${escapeHtml(prettyDate(capture.created_at))} · ${escapeHtml(capture.sensitivity)}</p>
        </div>
      </div>
      <p class="snippet">${escapeHtml((capture.selected_text || "").slice(0, 280))}</p>
      <div class="chips">
        <span class="chip ${capture.stance === "opposing" ? "warning-chip" : ""}">${escapeHtml(capture.stance || "neutral")}</span>
        ${(capture.review_tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}
        ${(capture.suggested_tags || []).slice(0, 4).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}
      </div>
    </article>
  `;
  els.reviewLastCaptureButton.disabled = false;
  els.markLastPrivateButton.disabled = capture.sensitivity === "sensitive";
}

function renderTopicCards(items) {
  els.topicCardCount.textContent = String(items.length);
  if (!items.length) {
    els.topicCards.innerHTML = "<p class='status'>Topic cards will appear as related captures accumulate.</p>";
    return;
  }

  els.topicCards.innerHTML = items
    .map(
      (item) => `
        <article class="facet">
          <div class="facet-head">
            <div>
              <h3>${escapeHtml(item.title)}</h3>
              <p class="facet-meta">support ${item.support_count} · oppose ${item.oppose_count} · ${escapeHtml(prettyDate(item.updated_at))}</p>
            </div>
          </div>
          <p class="snippet">${escapeHtml(item.summary)}</p>
          <div class="chips">
            ${(item.supporting_capture_ids || []).slice(0, 3).map((id) => `<span class="chip">${escapeHtml(id)}</span>`).join("")}
            ${(item.opposing_capture_ids || []).slice(0, 2).map((id) => `<span class="chip warning-chip">${escapeHtml(id)}</span>`).join("")}
          </div>
        </article>
      `
    )
    .join("");
}

async function refreshProfile() {
  try {
    const profile = await apiFetch("/profile");
    renderApproved(profile.approved);
    renderPending(profile.pending);
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

function renderApproved(items) {
  if (!items.length) {
    els.approvedProfile.innerHTML = "<p class='status'>No approved profile facets yet.</p>";
    return;
  }

  els.approvedProfile.innerHTML = items
    .map(
      (item) => `
        <article class="facet">
          <div class="facet-head">
            <div>
              <h3>${escapeHtml(item.label)}</h3>
              <p class="facet-meta">${escapeHtml(item.facet_type)} · approved ${escapeHtml(prettyDate(item.approved_at))}</p>
            </div>
          </div>
          <p class="snippet">${escapeHtml(item.claim_text)}</p>
          <div class="chips">
            ${(item.evidence_capture_ids || []).map((id) => `<span class="chip">${escapeHtml(id)}</span>`).join("")}
          </div>
        </article>
      `
    )
    .join("");
}

function renderPending(items) {
  if (!items.length) {
    els.pendingProfile.innerHTML = "<p class='status'>No pending suggestions right now.</p>";
    return;
  }

  els.pendingProfile.innerHTML = items
    .map(
      (item) => `
        <article class="facet">
          <div class="facet-head">
            <div>
              <h3>${escapeHtml(item.label)}</h3>
              <p class="facet-meta">${escapeHtml(item.facet_type)} · confidence ${item.confidence.toFixed(2)}</p>
            </div>
          </div>
          <p class="snippet">${escapeHtml(item.claim_text)}</p>
          <p class="result-meta">${escapeHtml(item.rationale)}</p>
          <div class="chips">
            ${(item.evidence_capture_ids || []).map((id) => `<span class="chip">${escapeHtml(id)}</span>`).join("")}
          </div>
          <div class="facet-actions">
            <button class="approve" data-approve="${escapeHtml(item.id)}">Approve</button>
            <button class="reject" data-reject="${escapeHtml(item.id)}">Reject</button>
          </div>
        </article>
      `
    )
    .join("");

  for (const button of document.querySelectorAll("[data-approve]")) {
    button.addEventListener("click", () => updateSuggestion(button.dataset.approve, "approve"));
  }
  for (const button of document.querySelectorAll("[data-reject]")) {
    button.addEventListener("click", () => updateSuggestion(button.dataset.reject, "reject"));
  }
}

async function updateSuggestion(id, action) {
  try {
    await apiFetch(`/profile-suggestions/${encodeURIComponent(id)}/${action}`, { method: "POST" });
    setSearchStatus(`Suggestion ${action}d.`);
    await Promise.all([refreshProfile(), refreshAiState()]);
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

function setSearchStatus(message, isError = false) {
  els.searchStatus.textContent = message;
  els.searchStatus.style.color = isError ? "#b42318" : "";
}
