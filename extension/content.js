(function () {
  let chip = null;
  let toast = null;
  let draftCache = null;
  let chatWrapupButton = null;
  let toastTimer = null;

  document.addEventListener(
    "mouseup",
    () => {
      window.setTimeout(refreshChip, 20);
    },
    true
  );

  document.addEventListener(
    "keyup",
    (event) => {
      if (event.key.startsWith("Arrow") || event.key === "Shift") {
        window.setTimeout(refreshChip, 20);
      }
    },
    true
  );

  document.addEventListener("scroll", removeChip, true);
  document.addEventListener(
    "mousedown",
    (event) => {
      if (chip && !chip.contains(event.target)) {
        removeChip();
      }
    },
    true
  );

  bootWrapupButton();

  function refreshChip() {
    const draft = buildDraftFromSelection();
    if (!draft) {
      removeChip();
      return;
    }
    draftCache = draft;
    renderChip(draft.rect);
  }

  function renderChip(rect) {
    if (!chip) {
      chip = document.createElement("div");
      chip.className = "mousekb-chip";

      const addButton = document.createElement("button");
      addButton.className = "mousekb-primary";
      addButton.textContent = "Add to KB";
      addButton.addEventListener("click", onFastSaveClicked);

      const panelButton = document.createElement("button");
      panelButton.className = "mousekb-secondary";
      panelButton.textContent = "Panel";
      panelButton.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        await chrome.runtime.sendMessage({ type: "open-side-panel" });
        removeChip();
      });

      chip.append(addButton, panelButton);
      document.documentElement.appendChild(chip);
    }

    const width = chip.offsetWidth || 180;
    const height = chip.offsetHeight || 44;
    const nextLeft = Math.max(12, Math.min(window.innerWidth - width - 12, rect.left));
    const nextTop = Math.max(12, Math.min(window.innerHeight - height - 12, rect.bottom + 10));
    chip.style.left = `${nextLeft}px`;
    chip.style.top = `${nextTop}px`;
  }

  async function onFastSaveClicked(event) {
    event.preventDefault();
    event.stopPropagation();
    if (!draftCache) {
      return;
    }
    const response = await chrome.runtime.sendMessage({
      type: "save-browser-capture",
      draft: draftCache
    });
    if (!response?.ok) {
      showToast({
        title: "MouseKB could not save that selection.",
        detail: response?.error || "Unknown error."
      });
      return;
    }
    removeChip();
    showCaptureToast(response.capture);
  }

  function showCaptureToast(capture) {
    showToast({
      title: `Saved ${capture.id} to your inbox.`,
      detail: capture.processing_stage === "queued"
        ? "MouseKB will finish the lightweight organization in the background."
        : "Saved and ready.",
      actions: [
        {
          label: "Add note",
          onClick: () => chrome.runtime.sendMessage({ type: "open-review-sheet", captureId: capture.id })
        },
        {
          label: "Review last",
          onClick: () => chrome.runtime.sendMessage({ type: "open-side-panel" })
        },
        {
          label: "Mark private",
          onClick: async () => {
            const response = await chrome.runtime.sendMessage({
              type: "mark-capture-private",
              captureId: capture.id
            });
            if (!response?.ok) {
              showToast({
                title: "Could not mark that capture private.",
                detail: response?.error || "Unknown error."
              });
              return;
            }
            showToast({
              title: `Marked ${capture.id} private.`,
              detail: "Sensitive captures stay out of the AI-facing memory layer."
            });
          }
        }
      ]
    });
  }

  function showToast({ title, detail = "", actions = [] }) {
    if (toastTimer) {
      window.clearTimeout(toastTimer);
      toastTimer = null;
    }
    if (toast) {
      toast.remove();
    }

    toast = document.createElement("aside");
    toast.className = "mousekb-toast";
    toast.innerHTML = `
      <div class="mousekb-toast-copy">
        <strong>${escapeHtml(title)}</strong>
        <p>${escapeHtml(detail)}</p>
      </div>
      <div class="mousekb-toast-actions"></div>
    `;
    const actionsHost = toast.querySelector(".mousekb-toast-actions");

    for (const action of actions) {
      const button = document.createElement("button");
      button.className = "mousekb-toast-button";
      button.textContent = action.label;
      button.addEventListener("click", async () => {
        try {
          await action.onClick();
        } finally {
          dismissToast();
        }
      });
      actionsHost.appendChild(button);
    }

    const closeButton = document.createElement("button");
    closeButton.className = "mousekb-toast-dismiss";
    closeButton.textContent = "Dismiss";
    closeButton.addEventListener("click", dismissToast);
    actionsHost.appendChild(closeButton);

    document.documentElement.appendChild(toast);
    toastTimer = window.setTimeout(dismissToast, 9000);
  }

  function dismissToast() {
    if (toastTimer) {
      window.clearTimeout(toastTimer);
      toastTimer = null;
    }
    if (toast) {
      toast.remove();
      toast = null;
    }
  }

  function removeChip() {
    draftCache = null;
    if (chip) {
      chip.remove();
      chip = null;
    }
  }

  function buildDraftFromSelection() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return null;
    }

    const text = selection.toString().trim();
    if (text.length < 3) {
      return null;
    }

    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) {
      return null;
    }

    const publicSource = !isLikelyPrivatePage();
    return {
      selected_text: text,
      page_url: location.href,
      page_title: document.title || location.hostname,
      page_snapshot_markdown: publicSource ? buildPageSnapshot() : "",
      is_public_source: publicSource,
      rect: {
        left: rect.left,
        bottom: rect.bottom
      }
    };
  }

  function bootWrapupButton() {
    if (!isAiChatPage()) {
      return;
    }
    renderWrapupButton();
    window.addEventListener("focus", renderWrapupButton);
  }

  function renderWrapupButton() {
    if (chatWrapupButton) {
      return;
    }
    chatWrapupButton = document.createElement("button");
    chatWrapupButton.className = "mousekb-wrapup";
    chatWrapupButton.textContent = "Save chat wrap-up";
    chatWrapupButton.addEventListener("click", onSaveChatWrapup);
    document.documentElement.appendChild(chatWrapupButton);
  }

  async function onSaveChatWrapup() {
    const messages = scrapeConversationMessages();
    if (!messages.length) {
      showToast({
        title: "MouseKB could not find a conversation to summarize.",
        detail: "Scroll the chat into view and try again."
      });
      return;
    }
    const payload = {
      source_app: inferAiSourceApp(),
      source_url: location.href,
      conversation_title: document.title || inferAiSourceApp(),
      messages
    };
    const response = await chrome.runtime.sendMessage({
      type: "save-chat-wrapup",
      payload
    });
    if (!response?.ok) {
      showToast({
        title: "MouseKB could not save that chat wrap-up.",
        detail: response?.error || "Unknown error."
      });
      return;
    }
    showToast({
      title: `Saved wrap-up ${response.wrapup.id}.`,
      detail: "Only the compact summary is kept, not the full transcript."
    });
  }

  function scrapeConversationMessages() {
    const candidates = [];
    const roleNodes = Array.from(document.querySelectorAll("[data-message-author-role]"));
    if (roleNodes.length >= 2) {
      for (const node of roleNodes.slice(-20)) {
        const content = cleanText(node.innerText || "");
        if (!content || content.length < 12) {
          continue;
        }
        candidates.push({
          role: node.getAttribute("data-message-author-role") || "unknown",
          content
        });
      }
      return dedupeMessages(candidates);
    }

    const articles = Array.from(document.querySelectorAll("main article, [role='main'] article"));
    if (articles.length >= 2) {
      for (const [index, node] of articles.slice(-20).entries()) {
        const content = cleanText(node.innerText || "");
        if (!content || content.length < 12) {
          continue;
        }
        candidates.push({
          role: index % 2 === 0 ? "user" : "assistant",
          content
        });
      }
      return dedupeMessages(candidates);
    }

    const blocks = Array.from(
      document.querySelectorAll("main p, main li, [role='main'] p, [role='main'] li")
    );
    for (const node of blocks.slice(-40)) {
      const content = cleanText(node.innerText || "");
      if (!content || content.length < 20) {
        continue;
      }
      candidates.push({
        role: "unknown",
        content
      });
    }
    return dedupeMessages(candidates).slice(-16);
  }

  function dedupeMessages(messages) {
    const seen = new Set();
    const deduped = [];
    for (const message of messages) {
      const key = `${message.role}::${message.content}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      deduped.push(message);
    }
    return deduped;
  }

  function cleanText(value) {
    return value.replace(/\s+/g, " ").trim().slice(0, 4000);
  }

  function inferAiSourceApp() {
    const host = location.hostname.toLowerCase();
    const href = location.href.toLowerCase();
    const title = (document.title || "").toLowerCase();
    if (href.includes("codex") || title.includes("codex")) {
      return "codex";
    }
    if (host.includes("chatgpt") || host.includes("openai")) {
      return "chatgpt";
    }
    if (host.includes("claude")) {
      return "claude";
    }
    return host.replace(/^www\./, "") || "ai-chat";
  }

  function isAiChatPage() {
    const host = location.hostname.toLowerCase();
    const href = location.href.toLowerCase();
    return (
      host.includes("chatgpt.com")
      || host.includes("chat.openai.com")
      || host.includes("claude.ai")
      || href.includes("/chat")
      || href.includes("/c/")
      || document.querySelector("[data-message-author-role]")
      || document.querySelector("main article")
    );
  }

  function isLikelyPrivatePage() {
    const host = location.hostname.toLowerCase();
    const href = location.href.toLowerCase();
    if (!/^https?:$/.test(location.protocol)) {
      return true;
    }
    if (host === "localhost" || host === "127.0.0.1") {
      return true;
    }
    const privatePatterns = [
      "mail.",
      "chat.",
      "claude.ai",
      "chatgpt.com",
      "openai.com",
      "slack.com",
      "discord.com",
      "web.whatsapp.com",
      "docs.google.com",
      "notion.so",
      "/messages",
      "/inbox"
    ];
    return privatePatterns.some((pattern) => host.includes(pattern) || href.includes(pattern));
  }

  function buildPageSnapshot() {
    const root = document.querySelector("article, main, [role='main']") || document.body;
    const nodes = Array.from(root.querySelectorAll("h1, h2, h3, p, li, blockquote, pre")).slice(0, 180);
    const lines = [`# ${document.title || "Untitled page"}`, "", `Source: ${location.href}`, ""];

    for (const node of nodes) {
      const text = (node.innerText || "").trim();
      if (!text) {
        continue;
      }
      const tagName = node.tagName.toLowerCase();
      if (tagName === "h1") {
        lines.push(`# ${text}`, "");
      } else if (tagName === "h2") {
        lines.push(`## ${text}`, "");
      } else if (tagName === "h3") {
        lines.push(`### ${text}`, "");
      } else if (tagName === "li") {
        lines.push(`- ${text}`);
      } else if (tagName === "blockquote") {
        lines.push(`> ${text}`, "");
      } else if (tagName === "pre") {
        lines.push("```", text, "```", "");
      } else {
        lines.push(text, "");
      }
    }

    return lines.join("\n").slice(0, 24000);
  }

  function escapeHtml(value) {
    return value
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
})();
