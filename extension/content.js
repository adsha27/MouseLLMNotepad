(function () {
  let chip = null;
  let draftCache = null;

  document.addEventListener("mouseup", () => {
    window.setTimeout(refreshChip, 20);
  }, true);

  document.addEventListener("keyup", (event) => {
    if (event.key.startsWith("Arrow") || event.key === "Shift") {
      window.setTimeout(refreshChip, 20);
    }
  }, true);

  document.addEventListener("scroll", removeChip, true);
  document.addEventListener("mousedown", (event) => {
    if (chip && !chip.contains(event.target)) {
      removeChip();
    }
  }, true);

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
      addButton.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const response = await chrome.runtime.sendMessage({
          type: "open-save-sheet",
          draft: draftCache
        });
        if (!response?.ok) {
          console.error(response?.error || "Could not open save sheet.");
        }
        removeChip();
      });

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
})();
