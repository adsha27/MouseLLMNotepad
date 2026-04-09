import {
  apiFetch,
  escapeHtml,
  prettyDate
} from "./shared.js";

const els = {
  openOptionsButton: document.querySelector("#openOptionsButton"),
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  searchStatus: document.querySelector("#searchStatus"),
  resultCount: document.querySelector("#resultCount"),
  results: document.querySelector("#results"),
  contextQuery: document.querySelector("#contextQuery"),
  contextMode: document.querySelector("#contextMode"),
  maxItems: document.querySelector("#maxItems"),
  buildContextButton: document.querySelector("#buildContextButton"),
  copyExportButton: document.querySelector("#copyExportButton"),
  contextExport: document.querySelector("#contextExport"),
  approvedProfile: document.querySelector("#approvedProfile"),
  pendingProfile: document.querySelector("#pendingProfile")
};

let latestResults = [];

boot().catch((error) => {
  setSearchStatus(error.message, true);
});

async function boot() {
  els.openOptionsButton.addEventListener("click", () => chrome.runtime.openOptionsPage());
  els.searchForm.addEventListener("submit", onSearch);
  els.buildContextButton.addEventListener("click", onBuildContext);
  els.copyExportButton.addEventListener("click", onCopyExport);
  await refreshProfile();
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
    latestResults = response.items;
    renderResults(response.items);
    els.contextQuery.value = query;
    setSearchStatus(`Loaded ${response.total} results.`);
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

async function onBuildContext() {
  const query = els.contextQuery.value.trim() || els.searchInput.value.trim();
  if (!query) {
    setSearchStatus("Add a query before building a context pack.");
    return;
  }

  const includeRawNoteIds = Array.from(document.querySelectorAll("[data-raw-note]:checked"))
    .map((checkbox) => checkbox.getAttribute("data-raw-note"))
    .filter(Boolean);

  setSearchStatus("Building context pack…");
  try {
    const response = await apiFetch("/context-packs", {
      method: "POST",
      body: {
        query,
        include_raw_note_ids: includeRawNoteIds,
        max_items: Number(els.maxItems.value || 6),
        mode: els.contextMode.value
      }
    });
    els.contextExport.value = response.export_text;
    setSearchStatus(`Context pack ${response.id} is ready.`);
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

async function onCopyExport() {
  if (!els.contextExport.value.trim()) {
    setSearchStatus("Build a context pack first.");
    return;
  }
  await navigator.clipboard.writeText(els.contextExport.value);
  setSearchStatus("Context pack copied to clipboard.");
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
            <label class="chip">
              <input type="checkbox" data-raw-note="${escapeHtml(item.id)}">
              raw
            </label>
          </div>
          <p class="snippet">${escapeHtml(item.snippet)}</p>
          <div class="chips">
            ${(item.reasons || []).map((reason) => `<span class="chip">${escapeHtml(reason)}</span>`).join("")}
            ${(item.suggested_tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}
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
    await refreshProfile();
  } catch (error) {
    setSearchStatus(error.message, true);
  }
}

function setSearchStatus(message, isError = false) {
  els.searchStatus.textContent = message;
  els.searchStatus.style.color = isError ? "#b42318" : "";
}
