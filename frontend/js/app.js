/* ============================================================
   ChatBot front-end logic
   Talks to the FastAPI backend via the same-origin /api proxy.
   ============================================================ */
(() => {
  "use strict";

  const API = ""; // same origin; nginx proxies /api -> backend

  // ===== Branding: change this one line to rename the whole app =====
  // (The backend can also override it via ASSISTANT_NAME in .env.)
  const APP_NAME = "ChatBot";

  // ---------- State ----------
  const state = {
    conversations: [],
    currentId: null,
    messages: [],
    models: [],
    model: localStorage.getItem("chat.model") || null,
    streaming: false,
    abort: null,
    demo: false,
    assistantName: APP_NAME,
    pendingAttachments: [], // [{id, filename}]
    webSearch: localStorage.getItem("chat.webSearch") === "1",
  };

  // ---------- DOM ----------
  const $ = (id) => document.getElementById(id);
  const el = {
    app: $("app"),
    sidebar: $("sidebar"),
    sidebarDivider: $("sidebarDivider"),
    convoList: $("convoList"),
    search: $("searchInput"),
    newChat: $("newChatBtn"),
    collapse: $("collapseBtn"),
    menu: $("menuBtn"),
    scrim: $("scrim"),
    theme: $("themeBtn"),
    themeIcon: $("themeIcon"),
    themeLabel: $("themeLabel"),
    clearAll: $("clearAllBtn"),
    modelBtn: $("modelBtn"),
    modelBtnLabel: $("modelBtnLabel"),
    modelMenu: $("modelMenu"),
    demoBadge: $("demoBadge"),
    thread: $("thread"),
    welcome: $("welcome"),
    messages: $("messages"),
    suggestions: $("suggestions"),
    input: $("input"),
    send: $("sendBtn"),
    stop: $("stopBtn"),
    plusBtn: $("plusBtn"),
    plusMenu: $("plusMenu"),
    menuUpload: $("menuUpload"),
    menuSearch: $("menuSearch"),
    menuSearchCheck: $("menuSearchCheck"),
    fileInput: $("fileInput"),
    attachments: $("attachments"),
    scrollBtn: $("scrollBtn"),
    toast: $("toast"),
  };

  // ---------- Utilities ----------
  const esc = (s) =>
    s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  function toast(msg, isError = false) {
    el.toast.textContent = msg;
    el.toast.classList.toggle("toast--error", isError);
    el.toast.hidden = false;
    requestAnimationFrame(() => el.toast.classList.add("show"));
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      el.toast.classList.remove("show");
      setTimeout(() => (el.toast.hidden = true), 260);
    }, 3200);
  }

  // Markdown rendering with graceful fallback if CDN libs are blocked.
  function renderMarkdown(text) {
    if (window.marked && window.DOMPurify) {
      marked.setOptions({ breaks: true, gfm: true });
      const html = marked.parse(text);
      return DOMPurify.sanitize(html);
    }
    return `<p>${esc(text).replace(/\n/g, "<br>")}</p>`;
  }

  // Post-process a rendered content node: wrap code blocks + highlight.
  function enhanceCode(node) {
    node.querySelectorAll("pre > code").forEach((code) => {
      const pre = code.parentElement;
      if (pre.parentElement.classList.contains("code-block")) return;
      const langClass = [...code.classList].find((c) => c.startsWith("language-"));
      const lang = langClass ? langClass.replace("language-", "") : "text";

      const wrap = document.createElement("div");
      wrap.className = "code-block";
      const head = document.createElement("div");
      head.className = "code-block__head";
      head.innerHTML = `<span class="code-block__lang">${esc(lang)}</span>`;
      const copy = document.createElement("button");
      copy.className = "code-copy";
      copy.innerHTML = copyIcon() + "<span>Copy</span>";
      copy.addEventListener("click", () => {
        copyText(code.textContent).then((ok) => copyFeedback(copy, ok));
      });
      head.appendChild(copy);

      pre.parentElement.insertBefore(wrap, pre);
      wrap.appendChild(head);
      wrap.appendChild(pre);
      if (window.hljs) {
        try { hljs.highlightElement(code); } catch (_) {}
      }
    });
  }

  const copyIcon = () =>
    '<svg viewBox="0 0 24 24" width="14" height="14"><rect x="9" y="9" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10" fill="none" stroke="currentColor" stroke-width="2"/></svg>';

  // Robust clipboard copy. The async Clipboard API only works in a secure
  // context (https or http://localhost). When the app is opened over a LAN IP
  // it is unavailable, so we fall back to a hidden-textarea + execCommand.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => fallbackCopy(text));
    }
    return Promise.resolve(fallbackCopy(text));
  }

  function fallbackCopy(text) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-9999px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (_) {
      return false;
    }
  }

  function copyFeedback(btn, ok) {
    const span = btn.querySelector("span");
    if (!span) return;
    span.textContent = ok ? "Copied!" : "Press Ctrl+C";
    setTimeout(() => (span.textContent = "Copy"), 1500);
  }

  // Render a grid of web image-search results into a message body (above text).
  function renderImageGrid(contentNode, images) {
    if (!images || !images.length) return;
    const body = contentNode.closest(".msg__body") || contentNode.parentElement;
    let grid = body.querySelector(".img-grid");
    if (!grid) {
      grid = document.createElement("div");
      grid.className = "img-grid";
      body.insertBefore(grid, contentNode); // images appear above the text
    }
    grid.innerHTML = "";
    images.forEach((im) => {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "img-grid__item";
      tile.title = im.title || "";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      // Remove the whole tile if the image fails to load (dead URL, hotlink
      // block, or not actually an image) — no broken-icon placeholders.
      img.onerror = () => {
        tile.remove();
        if (!grid.querySelector(".img-grid__item")) grid.remove();
      };
      img.src = im.img_src;
      tile.appendChild(img);
      // Click opens a full-size lightbox (not a redirect). Source link is inside.
      tile.addEventListener("click", () => openLightbox(im));
      grid.appendChild(tile);
    });
    scrollToBottom();
  }

  // Full-size image viewer (lightbox). Clicking a result opens this overlay;
  // only the explicit "Visit source" link navigates away.
  function openLightbox(im) {
    const overlay = document.createElement("div");
    overlay.className = "lightbox";
    overlay.innerHTML = `
      <div class="lightbox__inner">
        <img class="lightbox__img" src="${im.img_src}" alt="${esc(im.title || "")}">
        <div class="lightbox__bar">
          <span class="lightbox__title">${esc(im.title || "")}</span>
          <a class="lightbox__src" href="${im.url || im.img_src}" target="_blank" rel="noopener noreferrer">Visit source ↗</a>
        </div>
        <button class="lightbox__close" aria-label="Close">&times;</button>
      </div>`;
    const close = () => overlay.remove();
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay || e.target.classList.contains("lightbox__close")) close();
    });
    document.addEventListener("keydown", function onKey(e) {
      if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); }
    });
    document.body.appendChild(overlay);
  }

  // ---------- API ----------
  async function api(path, opts = {}) {
    const res = await fetch(API + path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  // ---------- Attachments / file upload ----------
  const fileIcon = () =>
    '<svg viewBox="0 0 24 24" width="15" height="15"><path d="M14 3v5h5M14 3l5 5v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>';

  function renderAttachments() {
    const list = state.pendingAttachments;
    el.attachments.hidden = list.length === 0;
    el.attachments.innerHTML = "";
    list.forEach((a) => {
      const chip = document.createElement("div");
      chip.className = "attach-chip" + (a.uploading ? " is-uploading" : "");
      const icon = a.uploading
        ? '<span class="spinner"></span>'
        : a.isImage && a.preview
        ? `<img class="attach-chip__thumb" src="${a.preview}" alt="" style="width:22px;height:22px;border-radius:5px;object-fit:cover;display:block">`
        : fileIcon();
      chip.innerHTML =
        `<span class="attach-chip__icon">${icon}</span>` +
        `<span class="attach-chip__name">${esc(a.filename)}</span>`;
      if (!a.uploading) {
        const x = document.createElement("button");
        x.className = "attach-chip__x";
        x.setAttribute("aria-label", "Remove " + a.filename);
        x.innerHTML =
          '<svg viewBox="0 0 24 24" width="14" height="14"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
        x.addEventListener("click", () => removeAttachment(a));
        chip.appendChild(x);
      }
      el.attachments.appendChild(chip);
    });
  }

  function removeAttachment(a) {
    state.pendingAttachments = state.pendingAttachments.filter((x) => x !== a);
    renderAttachments();
  }

  async function uploadFiles(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    for (const file of files) {
      const isImage = (file.type || "").startsWith("image/");
      const entry = {
        id: null,
        filename: file.name,
        uploading: true,
        isImage,
        preview: isImage ? URL.createObjectURL(file) : null,
      };
      state.pendingAttachments.push(entry);
      renderAttachments();
      try {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(API + "/api/upload", { method: "POST", body: fd });
        if (!res.ok) {
          let detail = "Upload failed";
          try { detail = (await res.json()).detail || detail; } catch (_) {}
          throw new Error(detail);
        }
        const data = await res.json();
        entry.id = data.id;
        entry.uploading = false;
        entry.truncated = data.truncated;
        if (data.kind) entry.isImage = data.kind === "image";
        renderAttachments();
        if (data.truncated) {
          toast(`"${file.name}" was large — using the first part only.`);
        }
      } catch (err) {
        removeAttachment(entry);
        toast(`${file.name}: ${err.message}`, true);
      }
    }
  }

  // Paste an image straight from the clipboard (Ctrl/Cmd+V).
  function handlePaste(e) {
    const items = (e.clipboardData || window.clipboardData)?.items;
    if (!items) return;
    const files = [];
    for (const it of items) {
      if (it.kind === "file" && (it.type || "").startsWith("image/")) {
        const f = it.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length) {
      e.preventDefault(); // don't also paste the image's file path as text
      uploadFiles(files);
    }
  }

  // Drag-and-drop files anywhere onto the app.
  function handleDrop(e) {
    e.preventDefault();
    el.app.classList.remove("drag-over");
    const dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length) uploadFiles(dt.files);
  }

  // ---------- Theme ----------
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("chat.theme", theme);
    const dark = theme === "dark";
    el.themeLabel.textContent = dark ? "Light mode" : "Dark mode";
    el.themeIcon.innerHTML = dark
      ? '<path d="M12 3v2M12 19v2M5 12H3M21 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M17.7 6.3l1.4-1.4M4.9 19.1l1.4-1.4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/>'
      : '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>';
    const hljsTheme = $("hljs-theme");
    if (hljsTheme)
      hljsTheme.href = dark
        ? "css/vendor/hljs-github-dark.min.css"
        : "css/vendor/hljs-github.min.css";
  }

  // ---------- Models ----------
  async function loadModels() {
    try {
      state.models = await api("/api/models");
    } catch (_) {
      state.models = [];
    }
    if (!state.model && state.models.length) {
      const def = state.models.find((m) => m.is_default) || state.models[0];
      state.model = def.id;
    }
    renderModelMenu();
  }

  function currentModelName() {
    const m = state.models.find((x) => x.id === state.model);
    return m ? m.name : state.model || "Model";
  }

  function renderModelMenu() {
    el.modelBtnLabel.textContent = currentModelName();
    el.modelMenu.innerHTML = "";
    state.models.forEach((m) => {
      const opt = document.createElement("div");
      opt.className = "model-option" + (m.id === state.model ? " selected" : "");
      opt.setAttribute("role", "option");
      opt.innerHTML = `
        <div class="model-option__name">${esc(m.name)}
          ${m.id === state.model ? '<span class="model-option__check">✓</span>' : ""}
        </div>
        <div class="model-option__id">${esc(m.id)}</div>
        ${m.description ? `<div class="model-option__desc">${esc(m.description)}</div>` : ""}`;
      opt.addEventListener("click", () => {
        state.model = m.id;
        localStorage.setItem("chat.model", m.id);
        renderModelMenu();
        closeModelMenu();
      });
      el.modelMenu.appendChild(opt);
    });
  }

  const openModelMenu = () => { el.modelMenu.classList.add("open"); el.modelBtn.setAttribute("aria-expanded", "true"); };
  const closeModelMenu = () => { el.modelMenu.classList.remove("open"); el.modelBtn.setAttribute("aria-expanded", "false"); };

  // ---------- Conversations ----------
  async function loadConversations() {
    try {
      state.conversations = await api("/api/conversations");
    } catch (_) {
      state.conversations = [];
    }
    renderSidebar();
  }

  function groupConversations(list) {
    const now = new Date();
    const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const today = startOfDay(now);
    const yesterday = today - 86400000;
    const week = today - 6 * 86400000;
    const groups = { Today: [], Yesterday: [], "Previous 7 days": [], Older: [] };
    list.forEach((c) => {
      const t = startOfDay(new Date(c.updated_at));
      if (t >= today) groups.Today.push(c);
      else if (t >= yesterday) groups.Yesterday.push(c);
      else if (t >= week) groups["Previous 7 days"].push(c);
      else groups.Older.push(c);
    });
    return groups;
  }

  function renderSidebar() {
    const q = (el.search.value || "").toLowerCase().trim();
    const list = state.conversations.filter((c) => c.title.toLowerCase().includes(q));
    el.convoList.innerHTML = "";

    if (!list.length) {
      el.convoList.innerHTML = `<div class="convo-empty">${q ? "No matching chats" : "No conversations yet.<br>Start a new chat!"}</div>`;
      return;
    }

    const groups = groupConversations(list);
    Object.entries(groups).forEach(([label, items]) => {
      if (!items.length) return;
      const head = document.createElement("div");
      head.className = "convo-group__label";
      head.textContent = label;
      el.convoList.appendChild(head);
      items.forEach((c) => el.convoList.appendChild(convoItem(c)));
    });
  }

  function convoItem(c) {
    const item = document.createElement("div");
    item.className = "convo-item" + (c.id === state.currentId ? " active" : "");
    item.dataset.id = c.id;

    const title = document.createElement("span");
    title.className = "convo-item__title";
    title.textContent = c.title;

    const actions = document.createElement("div");
    actions.className = "convo-item__actions";
    const renameBtn = iconBtn(
      '<svg viewBox="0 0 24 24" width="14" height="14"><path d="M4 20h4l10-10-4-4L4 16v4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
      "Rename"
    );
    const delBtn = iconBtn(
      '<svg viewBox="0 0 24 24" width="14" height="14"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
      "Delete", true
    );
    actions.append(renameBtn, delBtn);

    item.append(title, actions);

    item.addEventListener("click", () => selectConversation(c.id));
    renameBtn.addEventListener("click", (e) => { e.stopPropagation(); startRename(item, c); });
    delBtn.addEventListener("click", (e) => { e.stopPropagation(); deleteConversation(c.id); });
    return item;
  }

  function iconBtn(svg, title, danger = false) {
    const b = document.createElement("button");
    b.className = "convo-item__btn" + (danger ? " danger" : "");
    b.title = title;
    b.innerHTML = svg;
    return b;
  }

  function startRename(item, c) {
    const title = item.querySelector(".convo-item__title");
    const input = document.createElement("input");
    input.className = "convo-item__title-input";
    input.value = c.title;
    item.replaceChild(input, title);
    input.focus();
    input.select();
    const commit = async () => {
      const val = input.value.trim();
      if (val && val !== c.title) {
        try {
          await api(`/api/conversations/${c.id}`, { method: "PATCH", body: JSON.stringify({ title: val }) });
          c.title = val;
        } catch (e) { toast(e.message, true); }
      }
      await loadConversations();
    };
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") { input.value = c.title; input.blur(); }
    });
  }

  async function deleteConversation(id) {
    if (!confirm("Delete this conversation? This can't be undone.")) return;
    try {
      await api(`/api/conversations/${id}`, { method: "DELETE" });
      if (id === state.currentId) newChat();
      await loadConversations();
      toast("Conversation deleted");
    } catch (e) { toast(e.message, true); }
  }

  async function selectConversation(id) {
    if (state.streaming) stopGeneration();
    closeMobileSidebar();
    try {
      const convo = await api(`/api/conversations/${id}`);
      state.currentId = id;
      state.messages = convo.messages;
      if (convo.model) { state.model = convo.model; renderModelMenu(); }
      renderMessages();
      renderSidebar();
    } catch (e) { toast(e.message, true); }
  }

  function newChat() {
    if (state.streaming) stopGeneration();
    state.currentId = null;
    state.messages = [];
    renderMessages();
    renderSidebar();
    closeMobileSidebar();
    el.input.focus();
  }

  // ---------- Rendering messages ----------
  function renderMessages() {
    const empty = state.messages.length === 0;
    el.welcome.style.display = empty ? "" : "none";
    el.messages.innerHTML = "";
    state.messages.forEach((m) => el.messages.appendChild(messageEl(m)));
    scrollToBottom(true);
  }

  function messageEl(m) {
    const wrap = document.createElement("div");
    wrap.className = `msg msg--${m.role}`;

    const avatar = document.createElement("div");
    avatar.className = "msg__avatar";
    avatar.textContent = m.role === "user" ? "Y" : "✶";

    const body = document.createElement("div");
    body.className = "msg__body";
    const role = document.createElement("div");
    role.className = "msg__role";
    role.textContent = m.role === "user" ? "You" : state.assistantName;

    const content = document.createElement("div");
    content.className = "msg__content";
    if (m.role === "user") {
      content.textContent = m.content;
    } else {
      content.innerHTML = renderMarkdown(m.content || "");
      enhanceCode(content);
    }

    body.append(role, content);

    // Show attached files (image thumbnails or file chips) under a user message.
    if (m.role === "user" && m.attachments && m.attachments.length) {
      const files = document.createElement("div");
      files.className = "msg__files";
      m.attachments.forEach((att) => {
        // Support both legacy string names and {name,isImage,preview} objects.
        const a = typeof att === "string" ? { name: att } : att;
        if (a.isImage && a.preview) {
          const fig = document.createElement("span");
          fig.className = "msg__image";
          fig.innerHTML = `<img src="${a.preview}" alt="${esc(a.name)}" style="max-width:260px;max-height:260px;width:auto;height:auto;border-radius:10px;border:1px solid var(--border);display:block;object-fit:contain">`;
          files.appendChild(fig);
        } else {
          const f = document.createElement("span");
          f.className = "msg__file";
          f.innerHTML = fileIcon() + `<span>${esc(a.name)}</span>`;
          files.appendChild(f);
        }
      });
      body.appendChild(files);
    }

    if (m.role === "assistant" && m.images && m.images.length) {
      renderImageGrid(content, m.images);
    }
    if (m.role === "assistant" && m.content) body.appendChild(assistantActions(m, content));

    wrap.append(avatar, body);
    return wrap;
  }

  function assistantActions(m, contentNode) {
    const actions = document.createElement("div");
    actions.className = "msg__actions";
    const copy = document.createElement("button");
    copy.className = "msg__action";
    copy.innerHTML = copyIcon() + "<span>Copy</span>";
    copy.addEventListener("click", () => {
      copyText(m.content).then((ok) => copyFeedback(copy, ok));
    });
    actions.appendChild(copy);

    // Regenerate only for the final assistant message.
    const isLast = state.messages[state.messages.length - 1] === m;
    if (isLast && !state.streaming) {
      const regen = document.createElement("button");
      regen.className = "msg__action";
      regen.innerHTML =
        '<svg viewBox="0 0 24 24" width="14" height="14"><path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Retry</span>';
      regen.addEventListener("click", regenerate);
      actions.appendChild(regen);
    }
    return actions;
  }

  // ---------- Scrolling ----------
  function nearBottom() {
    const t = el.thread;
    return t.scrollHeight - t.scrollTop - t.clientHeight < 120;
  }
  function scrollToBottom(force = false) {
    if (force || nearBottom()) el.thread.scrollTop = el.thread.scrollHeight;
  }

  // ---------- Sending / streaming ----------
  async function sendMessage(text) {
    text = (text || el.input.value).trim();
    if (state.streaming) return;

    // Don't send while a file is still uploading.
    if (state.pendingAttachments.some((a) => a.uploading)) {
      toast("Still uploading — one moment…");
      return;
    }
    const ready = state.pendingAttachments.filter((a) => a.id);
    // Allow sending with only attachments (default to a summary request).
    if (!text && ready.length) text = "Summarize the attached document(s).";
    if (!text) return;

    el.input.value = "";
    autoGrow();
    el.welcome.style.display = "none";

    const attachmentIds = ready.map((a) => a.id);
    const attachmentMeta = ready.map((a) => ({
      name: a.filename,
      isImage: !!a.isImage,
      preview: a.preview || null,
    }));
    // Clear the composer's pending attachments now that they're sent.
    state.pendingAttachments = [];
    renderAttachments();

    // Optimistic user message
    const userMsg = { role: "user", content: text, attachments: attachmentMeta };
    state.messages.push(userMsg);
    el.messages.appendChild(messageEl(userMsg));

    // Assistant placeholder with typing indicator
    const placeholder = { role: "assistant", content: "" };
    state.messages.push(placeholder);
    const aEl = messageEl(placeholder);
    const contentNode = aEl.querySelector(".msg__content");
    contentNode.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
    el.messages.appendChild(aEl);
    scrollToBottom(true);

    setStreaming(true);
    state.abort = new AbortController();

    let acc = "";
    let firstToken = true;
    let renderQueued = false;

    const flush = () => {
      renderQueued = false;
      contentNode.innerHTML = renderMarkdown(acc);
      enhanceCode(contentNode);
      contentNode.classList.add("cursor");
      scrollToBottom();
    };

    try {
      const res = await fetch(API + "/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          conversation_id: state.currentId,
          model: state.model,
          attachment_ids: attachmentIds,
          web_search: state.webSearch === true ? true : null,
        }),
        signal: state.abort.signal,
      });
      if (!res.ok || !res.body) throw new Error("Request failed (" + res.status + ")");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const raw = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 2);
          if (!raw.startsWith("data:")) continue;
          let evt;
          try { evt = JSON.parse(raw.slice(5).trim()); } catch (_) { continue; }

          if (evt.type === "meta") {
            if (evt.searched) {
              contentNode.innerHTML =
                '<div class="searching">🔎 Searching the web…</div>';
            }
            if (evt.is_new) {
              state.currentId = evt.conversation_id;
              await loadConversations();
            }
          } else if (evt.type === "images") {
            placeholder.images = evt.images || [];
            renderImageGrid(contentNode, placeholder.images);
          } else if (evt.type === "delta") {
            if (firstToken) {
              firstToken = false;
              contentNode.classList.remove("typing");
              // Clear the "searching" placeholder once real tokens arrive.
              const s = contentNode.querySelector(".searching");
              if (s) s.remove();
            }
            acc += evt.content;
            placeholder.content = acc;
            if (!renderQueued) { renderQueued = true; requestAnimationFrame(flush); }
          } else if (evt.type === "done") {
            placeholder.content = acc;
          } else if (evt.type === "error") {
            throw new Error(evt.error);
          }
        }
      }

      // Final render (clear cursor, attach actions).
      contentNode.classList.remove("cursor");
      contentNode.innerHTML = renderMarkdown(acc || "_(empty response)_");
      enhanceCode(contentNode);
      const body = aEl.querySelector(".msg__body");
      const old = body.querySelector(".msg__actions");
      if (old) old.remove();
      body.appendChild(assistantActions(placeholder, contentNode));
      await loadConversations();
    } catch (err) {
      contentNode.classList.remove("cursor");
      if (err.name === "AbortError") {
        if (!acc) {
          // remove empty placeholder
          aEl.remove();
          state.messages.pop();
        } else {
          contentNode.innerHTML = renderMarkdown(acc);
          enhanceCode(contentNode);
        }
        toast("Generation stopped");
      } else {
        contentNode.innerHTML = `<p style="color:var(--danger)">⚠ ${esc(err.message)}</p>`;
        toast(err.message, true);
      }
    } finally {
      setStreaming(false);
      state.abort = null;
      scrollToBottom();
    }
  }

  function regenerate() {
    // Resend the most recent user message.
    const lastUser = [...state.messages].reverse().find((m) => m.role === "user");
    if (lastUser) sendMessage(lastUser.content);
  }

  function stopGeneration() {
    if (state.abort) state.abort.abort();
  }

  function setStreaming(on) {
    state.streaming = on;
    el.send.hidden = on;
    el.stop.hidden = !on;
    el.input.disabled = false;
  }

  // ---------- Composer ----------
  function autoGrow() {
    el.input.style.height = "auto";
    el.input.style.height = Math.min(el.input.scrollHeight, 220) + "px";
  }

  // ---------- Sidebar resize ----------
  let isResizing = false;
  function startResize(e) {
    isResizing = true;
    const startX = e.clientX;
    const startWidth = el.sidebar.offsetWidth;
    const minWidth = 200;
    const maxWidth = 480;

    function doResize(e) {
      if (!isResizing) return;
      const delta = e.clientX - startX;
      const newWidth = Math.max(minWidth, Math.min(maxWidth, startWidth + delta));
      el.sidebar.style.width = newWidth + "px";
      localStorage.setItem("chat.sidebarWidth", newWidth);
    }

    function stopResize() {
      isResizing = false;
      document.removeEventListener("mousemove", doResize);
      document.removeEventListener("mouseup", stopResize);
    }

    document.addEventListener("mousemove", doResize);
    document.addEventListener("mouseup", stopResize);
  }

  // ---------- Mobile sidebar ----------
  const openMobileSidebar = () => el.app.classList.add("mobile-open");
  const closeMobileSidebar = () => el.app.classList.remove("mobile-open");

  // ---------- Health / demo badge ----------
  function applyBranding() {
    const name = state.assistantName || APP_NAME;
    document.title = name + " — AI Chat";
    const brand = document.querySelector(".brand__name");
    if (brand) brand.textContent = name;
    if (el.input) el.input.placeholder = "Message " + name + "…";
    const wSub = document.querySelector(".welcome__sub");
    if (wSub)
      wSub.textContent =
        "Ask anything, or attach a document and ask about it. I stream answers in real time and remember the conversation.";
    const hint = document.querySelector(".composer__hint");
    if (hint)
      hint.innerHTML =
        name +
        " can make mistakes. Press <kbd>Enter</kbd> to send, <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line.";
  }

  async function checkHealth() {
    try {
      const h = await api("/health");
      state.demo = !h.llm_enabled;
      el.demoBadge.hidden = !state.demo;
      if (h.assistant_name) {
        state.assistantName = h.assistant_name;
        applyBranding();
      }
    } catch (_) {}
  }

  // ---------- Events ----------
  function bind() {
    // Sidebar resize
    if (el.sidebarDivider) {
      el.sidebarDivider.addEventListener("mousedown", startResize);
    }

    el.send.addEventListener("click", () => sendMessage());
    el.stop.addEventListener("click", stopGeneration);
    el.newChat.addEventListener("click", newChat);

    // ---- "+" menu (upload + web search toggle), ChatGPT-style ----
    const openPlusMenu = () => {
      el.plusMenu.hidden = false;
      el.plusBtn.setAttribute("aria-expanded", "true");
      el.plusBtn.classList.add("is-open");
    };
    const closePlusMenu = () => {
      el.plusMenu.hidden = true;
      el.plusBtn.setAttribute("aria-expanded", "false");
      el.plusBtn.classList.remove("is-open");
    };
    function reflectSearch() {
      const on = state.webSearch;
      el.menuSearch.setAttribute("aria-checked", on ? "true" : "false");
      el.menuSearch.classList.toggle("is-active", on);
      el.menuSearchCheck.style.display = on ? "block" : "none";
      if (on) el.menuSearchCheck.removeAttribute("hidden");
      else el.menuSearchCheck.setAttribute("hidden", "");
      // Subtle hint on the + button itself when search is armed.
      el.plusBtn.classList.toggle("search-on", on);
    }
    reflectSearch();

    el.plusBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      el.plusMenu.hidden ? openPlusMenu() : closePlusMenu();
    });
    el.menuUpload.addEventListener("click", () => {
      closePlusMenu();
      el.fileInput.click();
    });
    el.menuSearch.addEventListener("click", () => {
      state.webSearch = !state.webSearch;
      localStorage.setItem("chat.webSearch", state.webSearch ? "1" : "0");
      reflectSearch();
      // Keep the menu open so the user sees the toggle change, ChatGPT-style.
    });
    // Close the menu when clicking outside it.
    document.addEventListener("click", (e) => {
      if (!el.plusMenu.hidden &&
          !el.plusMenu.contains(e.target) &&
          !el.plusBtn.contains(e.target)) {
        closePlusMenu();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !el.plusMenu.hidden) closePlusMenu();
    });
    el.fileInput.addEventListener("change", (e) => {
      uploadFiles(e.target.files);
      el.fileInput.value = ""; // allow re-selecting the same file
    });

    // Paste an image from the clipboard (Ctrl/Cmd+V). Bound once on document;
    // it bubbles up from the textarea, so binding both would double-fire.
    document.addEventListener("paste", handlePaste);

    // Drag-and-drop images/files anywhere onto the window.
    window.addEventListener("dragover", (e) => {
      e.preventDefault();
      el.app.classList.add("drag-over");
    });
    window.addEventListener("dragleave", (e) => {
      if (e.relatedTarget === null) el.app.classList.remove("drag-over");
    });
    window.addEventListener("drop", handleDrop);

    el.input.addEventListener("input", autoGrow);
    el.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    el.search.addEventListener("input", renderSidebar);

    el.collapse.addEventListener("click", () => {
      const collapsed = el.app.classList.toggle("collapsed");
      localStorage.setItem("chat.collapsed", collapsed ? "1" : "0");
    });
    // Top-left button: on mobile it slides the sidebar in/out; on desktop it
    // toggles the collapsed state (so a collapsed sidebar can always return).
    el.menu.addEventListener("click", () => {
      if (window.matchMedia("(max-width: 820px)").matches) {
        el.app.classList.toggle("mobile-open");
      } else {
        const collapsed = el.app.classList.toggle("collapsed");
        localStorage.setItem("chat.collapsed", collapsed ? "1" : "0");
      }
    });
    el.scrim.addEventListener("click", closeMobileSidebar);

    el.theme.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
    });

    el.clearAll.addEventListener("click", async () => {
      if (!state.conversations.length) return;
      if (!confirm("Delete ALL conversations? This cannot be undone.")) return;
      try {
        await api("/api/conversations", { method: "DELETE" });
        newChat();
        await loadConversations();
        toast("All conversations cleared");
      } catch (e) { toast(e.message, true); }
    });

    // Model dropdown
    el.modelBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      el.modelMenu.classList.contains("open") ? closeModelMenu() : openModelMenu();
    });
    document.addEventListener("click", (e) => {
      if (!$("modelSelect").contains(e.target)) closeModelMenu();
    });

    // Suggestion chips
    el.suggestions.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (chip) sendMessage(chip.dataset.prompt);
    });

    // Scroll-to-bottom button
    el.thread.addEventListener("scroll", () => {
      el.scrollBtn.hidden = nearBottom();
    });
    el.scrollBtn.addEventListener("click", () => scrollToBottom(true));
  }

  // ---------- Init ----------
  async function init() {
    applyTheme(localStorage.getItem("chat.theme") || "dark");
    if (localStorage.getItem("chat.collapsed") === "1") el.app.classList.add("collapsed");
    const savedWidth = localStorage.getItem("chat.sidebarWidth");
    if (savedWidth) el.sidebar.style.width = savedWidth + "px";
    bind();
    applyBranding();
    autoGrow();
    await Promise.all([loadModels(), loadConversations(), checkHealth()]);
    el.input.focus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();