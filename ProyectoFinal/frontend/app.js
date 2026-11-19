/* Dev Knowledge Assistant — chat UI over the FastAPI backend (same origin). */
(() => {
  "use strict";

  const KEY_STORAGE = "devkb.apiKey";
  const DOC_TYPES = {
    standard: { label: "Standards", icon: "i-book" },
    guide: { label: "Guides", icon: "i-file" },
    troubleshooting: { label: "Troubleshooting", icon: "i-wrench" },
    runbook: { label: "Runbooks", icon: "i-rocket" },
    snippet: { label: "Snippets", icon: "i-code" },
    issue: { label: "Issues", icon: "i-bug" },
    reference: { label: "Reference", icon: "i-file" },
  };
  const STATUS = {
    answered: { label: "Answered", icon: "i-check" },
    general: { label: "General answer · not in docs", icon: "i-globe" },
    no_answer: { label: "Insufficient context", icon: "i-alert" },
    fallback: { label: "Not in the docs", icon: "i-alert" },
    degraded: { label: "LLM offline · excerpts", icon: "i-alert" },
    error: { label: "Error", icon: "i-x" },
  };
  const SUGGESTIONS = {
    ask: [
      { cat: "Troubleshooting", icon: "i-wrench", text: "How do we handle database connection pool exhaustion?" },
      { cat: "Runbooks", icon: "i-rocket", text: "How do I roll back a bad deployment?" },
      { cat: "Standards", icon: "i-git", text: "What is the commit message format?" },
      { cat: "Incidents", icon: "i-bug", text: "Why did customers get charged twice?" },
    ],
    snippets: [
      { cat: "Resilience", icon: "i-code", text: "retry with exponential backoff" },
      { cat: "Database", icon: "i-code", text: "database session that never leaks connections" },
      { cat: "API", icon: "i-code", text: "cursor pagination for list endpoints" },
      { cat: "Observability", icon: "i-code", text: "structured JSON logging with correlation id" },
    ],
  };
  const LOADING_STAGES = ["Retrieving documentation…", "Grading context…", "Asking the model via n8n…", "Checking citations…"];

  const $ = (sel) => document.querySelector(sel);
  const el = {
    thread: $("#thread"), hero: $("#hero"), suggestions: $("#suggestions"),
    form: $("#composer"), input: $("#composer-input"), send: $("#send-btn"), label: $("#composer-label"),
    chips: $("#scope-chips"), docList: $("#doc-list"), docCount: $("#doc-count"), scopePill: $("#scope-pill"),
    status: $("#status"), statusText: $("#status-text"),
    settings: $("#settings"), keyInput: $("#api-key-input"), keyError: $("#api-key-error"),
    drawer: $("#drawer"), drawerTitle: $("#drawer-title"), drawerMeta: $("#drawer-meta"), drawerBody: $("#drawer-body"),
    sidebar: $("#sidebar"), scrim: $("#scrim"), toast: $("#toast"),
    review: $("#review"), reviewTab: $("#tab-review"), reviewCount: $("#review-count"),
    draftList: $("#draft-list"), draftPane: $("#draft-pane"), reviewFilter: $("#review-filter"),
    confirm: $("#confirm"),
  };

  const state = {
    apiKey: readKey(),
    mode: "ask",
    scope: null,
    busy: false,
    docs: [],
    docIds: new Set(),
    lastFocus: null,
    role: null,
    reviewStatus: "pending",
    drafts: [],
    selectedDraft: null,
  };

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  function readKey() {
    try { return localStorage.getItem(KEY_STORAGE) || ""; } catch { return ""; }
  }
  function writeKey(value) {
    try { localStorage.setItem(KEY_STORAGE, value); } catch { /* private mode: keep in memory */ }
  }
  function icon(id) {
    return `<svg class="icon" aria-hidden="true"><use href="#${id}"/></svg>`;
  }
  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function node(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }
  let toastTimer;
  function toast(message) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.hidden = true; }, 2600);
  }
  function scrollToEnd() {
    el.thread.scrollTop = el.thread.scrollHeight;
  }

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function api(path, options = {}) {
    const headers = { "X-API-Key": state.apiKey, ...(options.body ? { "Content-Type": "application/json" } : {}) };
    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch {
      throw new ApiError(0, "Cannot reach the API. Is uvicorn running?");
    }
    if (response.status === 401) {
      openSettings("That API key was rejected. Check API_KEYS in .env.");
      throw new ApiError(401, "Unauthorized");
    }
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        detail = typeof body.detail === "string" ? body.detail : (body.detail?.[0]?.msg || detail);
      } catch { /* non-JSON error */ }
      throw new ApiError(response.status, detail);
    }
    return response.json();
  }

  // ---------------------------------------------------------------------------
  // Markdown rendering: sanitized, highlighted, with copy buttons and citation chips
  // ---------------------------------------------------------------------------

  marked.setOptions({ gfm: true, breaks: false });

  function renderMarkdown(target, markdown) {
    target.innerHTML = DOMPurify.sanitize(marked.parse(markdown || ""));
    enhanceCode(target);
    linkCitations(target);
  }

  function enhanceCode(root) {
    root.querySelectorAll("pre > code").forEach((code) => {
      const pre = code.parentElement;
      const lang = ([...code.classList].find((c) => c.startsWith("language-")) || "").replace("language-", "");
      try { hljs.highlightElement(code); } catch { /* unknown language */ }
      const wrapper = node(`
        <div class="code-block">
          <div class="code-head"><span>${escapeHtml(lang || "code")}</span>
            <button type="button" class="copy-btn">${icon("i-copy")}<span>Copy</span></button>
          </div>
        </div>`);
      pre.replaceWith(wrapper);
      wrapper.appendChild(pre);
      wrapper.querySelector(".copy-btn").addEventListener("click", (event) => copyText(code.innerText, event.currentTarget));
    });
  }

  function linkCitations(root) {
    const pattern = /\[([A-Za-z0-9][A-Za-z0-9_.\-]*)\]/g;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement.closest("pre, code, a, button") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const hasCitation = /\[[A-Za-z0-9][A-Za-z0-9_.\-]*\]/;  // non-global: no lastIndex state between nodes
    const targets = [];
    while (walker.nextNode()) if (hasCitation.test(walker.currentNode.nodeValue)) targets.push(walker.currentNode);

    targets.forEach((textNode) => {
      const fragment = document.createDocumentFragment();
      let last = 0;
      const text = textNode.nodeValue;
      text.replace(pattern, (match, id, offset) => {
        if (!state.docIds.has(id)) return match;
        fragment.append(text.slice(last, offset));
        const chip = node(`<button type="button" class="cite" aria-label="Open source ${escapeHtml(id)}">${escapeHtml(id)}</button>`);
        chip.addEventListener("click", () => openDocument(id));
        fragment.append(chip);
        last = offset + match.length;
        return match;
      });
      fragment.append(text.slice(last));
      textNode.replaceWith(fragment);
    });
  }

  async function copyText(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      if (button) {
        button.classList.add("copied");
        const label = button.querySelector("span");
        if (label) label.textContent = "Copied";
        setTimeout(() => { button.classList.remove("copied"); if (label) label.textContent = "Copy"; }, 1600);
      } else {
        toast("Copied to clipboard");
      }
    } catch {
      toast("Clipboard is not available in this browser");
    }
  }

  // ---------------------------------------------------------------------------
  // Sidebar: health, scope chips, document list
  // ---------------------------------------------------------------------------

  async function loadHealth() {
    try {
      const response = await fetch("/health");
      const { index } = await response.json();
      const webhook = index.llm_configured ? "n8n webhook set" : "n8n webhook missing";
      el.status.dataset.state = index.llm_configured ? "ok" : "warn";
      el.statusText.textContent = `${index.documents} docs · ${index.chunks} chunks · ${webhook}`;
    } catch {
      el.status.dataset.state = "error";
      el.statusText.textContent = "API unreachable";
    }
  }

  function renderScopeChips() {
    const types = [...new Set(state.docs.map((d) => d.doc_type))];
    const options = [{ value: null, label: "All" }, ...types.map((t) => ({ value: t, label: DOC_TYPES[t]?.label || t }))];
    el.chips.innerHTML = "";
    options.forEach((option) => {
      const chip = node(`<button type="button" class="chip" role="radio">${escapeHtml(option.label)}</button>`);
      chip.setAttribute("aria-checked", String(state.scope === option.value));
      chip.addEventListener("click", () => setScope(option.value));
      el.chips.appendChild(chip);
    });
  }

  function setScope(value) {
    state.scope = value;
    renderScopeChips();
    el.scopePill.hidden = !value || state.mode !== "ask";
    el.scopePill.textContent = value ? `scope: ${value}` : "";
  }

  async function loadDocuments() {
    try {
      state.docs = await api("/api/v1/documents");
    } catch (error) {
      el.docList.innerHTML = `<p class="muted">${escapeHtml(error.status === 401 ? "Add your API key to load documents." : error.message)}</p>`;
      return;
    }
    state.docIds = new Set(state.docs.map((d) => d.doc_id));
    el.docCount.textContent = state.docs.length;

    const groups = {};
    state.docs.forEach((doc) => { (groups[doc.doc_type] ||= []).push(doc); });
    el.docList.innerHTML = "";
    Object.keys(DOC_TYPES).filter((t) => groups[t]).concat(Object.keys(groups).filter((t) => !DOC_TYPES[t])).forEach((type) => {
      const meta = DOC_TYPES[type] || { label: type, icon: "i-file" };
      const group = node(`<div class="doc-group"><p class="doc-group-title">${icon(meta.icon)}${escapeHtml(meta.label)}</p></div>`);
      groups[type].forEach((doc) => {
        const item = node(`<button type="button" class="doc-item" title="${escapeHtml(doc.title)}">${escapeHtml(doc.title)}</button>`);
        item.dataset.docId = doc.doc_id;
        item.addEventListener("click", () => { openDocument(doc.doc_id); closeSidebar(); });
        group.appendChild(item);
      });
      el.docList.appendChild(group);
    });
    renderScopeChips();
  }

  // ---------------------------------------------------------------------------
  // Hero / suggestions / mode
  // ---------------------------------------------------------------------------

  function renderSuggestions() {
    el.suggestions.innerHTML = "";
    SUGGESTIONS[state.mode].forEach((s) => {
      const card = node(`
        <button type="button" class="suggestion">
          <span class="s-icon">${icon(s.icon)}</span>
          <span><span class="s-cat">${escapeHtml(s.cat)}</span><span class="s-text" style="display:block">${escapeHtml(s.text)}</span></span>
        </button>`);
      card.addEventListener("click", () => submit(s.text));
      el.suggestions.appendChild(card);
    });
  }

  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      const active = btn.dataset.mode === mode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    const reviewing = mode === "review";
    el.review.hidden = !reviewing;
    el.thread.hidden = reviewing;
    el.form.hidden = reviewing;
    if (reviewing) {
      el.scopePill.hidden = true;
      loadDrafts();
      return;
    }
    el.label.textContent = mode === "ask" ? "Ask a technical question" : "Describe the code you need";
    el.input.placeholder = mode === "ask"
      ? "e.g. How should I retry calls to a flaky downstream API?"
      : "e.g. retry with exponential backoff";
    el.scopePill.hidden = !state.scope || mode !== "ask";
    renderSuggestions();
    el.input.focus();
  }

  function newConversation() {
    if (state.mode === "review") setMode("ask");
    el.thread.querySelectorAll(".msg").forEach((m) => m.remove());
    el.hero.hidden = false;
    el.input.value = "";
    autoSize();
    closeSidebar();
    el.input.focus();
  }

  // ---------------------------------------------------------------------------
  // Conversation
  // ---------------------------------------------------------------------------

  function addUserMessage(text) {
    const msg = node(`<div class="msg msg-user"><div class="bubble-user"></div></div>`);
    msg.querySelector(".bubble-user").textContent = text;
    el.thread.appendChild(msg);
  }

  function addThinking() {
    const msg = node(`
      <div class="msg">
        <div class="msg-head"><span class="avatar">${icon("i-terminal")}</span><span class="msg-name">devkb</span></div>
        <div class="answer-card thinking">
          <p class="thinking-label"><span class="spinner"></span><span class="stage">${LOADING_STAGES[0]}</span></p>
          <div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>
        </div>
      </div>`);
    el.thread.appendChild(msg);
    let stage = 0;
    const timer = state.mode === "ask"
      ? setInterval(() => {
          stage = Math.min(stage + 1, LOADING_STAGES.length - 1);
          msg.querySelector(".stage").textContent = LOADING_STAGES[stage];
        }, 1400)
      : null;
    return { msg, stop: () => clearInterval(timer) };
  }

  function stepTone(step) {
    if (step.startsWith("grade_context")) return step.includes(": True") ? "ok" : "warn";
    if (step.startsWith("rewrite_question") || step.startsWith("general_answer")) return "info";
    if (step.startsWith("fallback_answer") || step.includes("degraded") || step.includes("declined")) return "warn";
    if (step.startsWith("generate_answer")) return "ok";
    return "";
  }

  function renderTrace(trace) {
    const items = trace.map((step) => {
      const match = step.match(/^([a-z_]+)(.*)$/);
      const name = match ? match[1] : step;
      const detail = match ? match[2].replace(/^[:\s]+/, "") : "";
      return `<li class="step" data-tone="${stepTone(step)}"><span class="step-dot"></span>
        <div><p class="step-name">${escapeHtml(name)}</p>${detail ? `<p class="step-detail">${escapeHtml(detail)}</p>` : ""}</div></li>`;
    }).join("");
    return `<details class="trace"><summary>${icon("i-chevron")} LangGraph trace · ${trace.length} steps</summary><ol class="steps">${items}</ol></details>`;
  }

  function renderSources(citations) {
    if (!citations.length) return "";
    const cards = citations.map((c) => `
      <button type="button" class="source" data-doc-id="${escapeHtml(c.doc_id)}">
        <span class="source-id">[${escapeHtml(c.doc_id)}]</span>
        <span class="source-title">${escapeHtml(c.title)}</span>
        <span class="source-section">${escapeHtml(c.section)}</span>
        <span class="score"><span class="score-bar"><span style="width:${Math.min(100, Math.round(c.score * 100))}%"></span></span>${c.score.toFixed(2)}</span>
      </button>`).join("");
    return `<p class="section-label">Sources</p><div class="sources">${cards}</div>`;
  }

  function renderAnswer(container, result) {
    const status = STATUS[result.status] || STATUS.error;
    const meta = [
      `score ${result.best_score.toFixed(2)}`,
      result.attempts ? `${result.attempts} rewrite${result.attempts > 1 ? "s" : ""}` : null,
    ].filter(Boolean).join(" · ");
    const isGeneral = result.status === "general";
    const warnings = (result.warnings || [])
      .filter((w) => !(isGeneral && w.startsWith("Not found in the internal documentation")))
      .map((w) => `<p class="warning">${icon("i-alert")}<span>${escapeHtml(w)}</span></p>`).join("");
    const callout = isGeneral ? `
      <div class="callout">${icon("i-globe")}<div>
        <strong>Not in the internal documentation</strong>
        <span>This is a general answer from the model. Verify it before applying it. It was sent to the admins for review${result.draft_id ? ` (draft <code>${escapeHtml(result.draft_id)}</code>)` : ""}; once approved it becomes company documentation.</span>
      </div></div>` : "";

    container.innerHTML = `
      <div class="msg-head">
        <span class="avatar">${icon("i-terminal")}</span><span class="msg-name">devkb</span>
        <span class="badge badge-${escapeHtml(result.status)}">${icon(status.icon)}${status.label}</span>
        <span class="meta-chip">${escapeHtml(meta)}</span>
        <span class="msg-actions"><button type="button" class="icon-btn copy-answer" aria-label="Copy answer">${icon("i-copy")}</button></span>
      </div>
      ${callout}
      <div class="answer-card markdown${isGeneral ? " general" : ""}"></div>
      ${warnings}
      ${renderSources(result.citations)}
      ${renderTrace(result.trace || [])}`;

    renderMarkdown(container.querySelector(".answer-card"), result.answer);
    container.querySelector(".copy-answer").addEventListener("click", () => copyText(result.answer));
    container.querySelectorAll(".source").forEach((card) => card.addEventListener("click", () => openDocument(card.dataset.docId)));
  }

  function renderSnippets(container, query, results) {
    const head = `<div class="msg-head"><span class="avatar">${icon("i-code")}</span><span class="msg-name">snippets</span>
      <span class="meta-chip">${results.length} match${results.length === 1 ? "" : "es"} for “${escapeHtml(query)}”</span></div>`;
    if (!results.length) {
      container.innerHTML = `${head}<p class="empty">No approved snippets match that description.</p>`;
      return;
    }
    container.innerHTML = head + results.map((r, i) => `
      <article class="snippet">
        <div class="snippet-head">
          <span class="snippet-title">${escapeHtml(r.title)}</span>
          <button type="button" class="cite" data-doc-id="${escapeHtml(r.doc_id)}">${escapeHtml(r.doc_id)}</button>
          <span class="meta-chip">similarity ${r.score.toFixed(2)}${r.language ? " · " + escapeHtml(r.language) : ""}</span>
        </div>
        <div class="markdown" data-index="${i}"></div>
      </article>`).join("");
    results.forEach((r, i) => {
      // Strip the leading "# Title" — it is already shown in the card header.
      renderMarkdown(container.querySelector(`[data-index="${i}"]`), r.text.replace(/^#\s+.*\n+/, ""));
    });
    container.querySelectorAll(".snippet-head .cite").forEach((chip) => chip.addEventListener("click", () => openDocument(chip.dataset.docId)));
  }

  function renderError(container, error) {
    container.innerHTML = `
      <div class="msg-head"><span class="avatar">${icon("i-terminal")}</span><span class="msg-name">devkb</span>
        <span class="badge badge-error">${icon("i-x")}Request failed</span></div>
      <p class="warning">${icon("i-alert")}<span>${escapeHtml(error.message)}</span></p>`;
  }

  async function submit(text) {
    const question = (text ?? el.input.value).trim();
    if (!question || state.busy) return;
    if (!state.apiKey) { openSettings(); return; }

    state.busy = true;
    el.send.disabled = true;
    el.thread.setAttribute("aria-busy", "true");
    el.hero.hidden = true;
    el.input.value = "";
    autoSize();

    addUserMessage(question);
    const { msg, stop } = addThinking();
    scrollToEnd();

    try {
      if (state.mode === "ask") {
        const result = await api("/api/v1/assistant/ask", {
          method: "POST",
          body: JSON.stringify({ question, doc_type: state.scope }),
        });
        renderAnswer(msg, result);
        if (result.draft_id) refreshPendingCount();
      } else {
        const params = new URLSearchParams({ q: question, k: "3" });
        const { results } = await api(`/api/v1/snippets/search?${params}`);
        renderSnippets(msg, question, results);
      }
    } catch (error) {
      if (error.status === 401) msg.remove();
      else renderError(msg, error);
    } finally {
      stop();
      state.busy = false;
      el.send.disabled = false;
      el.thread.setAttribute("aria-busy", "false");
      scrollToEnd();
      el.input.focus();
    }
  }

  // ---------------------------------------------------------------------------
  // Document drawer
  // ---------------------------------------------------------------------------

  async function openDocument(docId) {
    state.lastFocus = document.activeElement;
    el.drawer.hidden = false;
    el.drawerMeta.textContent = docId;
    el.drawerTitle.textContent = "Loading…";
    el.drawerBody.innerHTML = `<div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>`;
    document.querySelectorAll(".doc-item").forEach((i) => i.setAttribute("aria-current", String(i.dataset.docId === docId)));
    $("#close-drawer").focus();
    try {
      const doc = await api(`/api/v1/documents/${encodeURIComponent(docId)}`);
      el.drawerMeta.textContent = `[${doc.doc_id}] · ${doc.doc_type} · ${doc.source_path}`;
      el.drawerTitle.textContent = doc.title;
      renderMarkdown(el.drawerBody, doc.text.replace(/^#\s+.*\n+/, ""));
    } catch (error) {
      el.drawerTitle.textContent = "Could not open document";
      el.drawerBody.innerHTML = `<p class="warning">${icon("i-alert")}<span>${escapeHtml(error.message)}</span></p>`;
    }
  }

  function closeDrawer() {
    if (el.drawer.hidden) return;
    el.drawer.hidden = true;
    document.querySelectorAll(".doc-item").forEach((i) => i.removeAttribute("aria-current"));
    state.lastFocus?.focus?.();
  }

  // ---------------------------------------------------------------------------
  // Settings dialog
  // ---------------------------------------------------------------------------

  function openSettings(error = "") {
    el.keyInput.value = state.apiKey;
    el.keyError.textContent = error;
    if (!el.settings.open) el.settings.showModal();
    el.keyInput.focus();
  }

  async function saveSettings(event) {
    event.preventDefault();
    const value = el.keyInput.value.trim();
    if (!value) { el.keyError.textContent = "Enter an API key."; return; }
    state.apiKey = value;
    writeKey(value);
    el.keyError.textContent = "";
    el.settings.close();
    await Promise.all([loadDocuments(), loadMe()]);
    if (state.docs.length) toast("Connected");
  }

  // ---------------------------------------------------------------------------
  // Mobile sidebar
  // ---------------------------------------------------------------------------

  function openSidebar() {
    el.sidebar.classList.add("open");
    el.scrim.hidden = false;
    $("#close-sidebar").focus();
  }
  function closeSidebar() {
    el.sidebar.classList.remove("open");
    el.scrim.hidden = true;
  }

  // ---------------------------------------------------------------------------
  // Composer
  // ---------------------------------------------------------------------------

  function autoSize() {
    el.input.style.height = "auto";
    el.input.style.height = `${Math.min(el.input.scrollHeight, 200)}px`;
  }

  // ---------------------------------------------------------------------------
  // Review queue (admin): pending general answers -> company documentation
  // ---------------------------------------------------------------------------

  const FIELD_RULES = {
    title: (v) => (v.trim().length >= 3 ? "" : "Title needs at least 3 characters."),
    doc_id: (v) => {
      if (!/^[a-z0-9][a-z0-9-]{2,59}$/.test(v)) return "Use 3–60 lowercase letters, numbers or dashes.";
      if (state.docIds.has(v)) return "A document with this ID already exists. Choose another one.";
      return "";
    },
    content: (v) => (v.trim().length >= 20 ? "" : "Content needs at least 20 characters."),
  };
  const FIELD_IDS = { title: "f-title", doc_id: "f-docid", content: "f-content" };
  const FIELD_LABELS = { title: "Title", doc_id: "Document ID", content: "Content" };

  async function loadMe() {
    try {
      state.role = (await api("/api/v1/me")).role;
    } catch {
      state.role = null;
    }
    const isAdmin = state.role === "admin";
    el.reviewTab.hidden = !isAdmin;
    if (isAdmin) refreshPendingCount();
    else if (state.mode === "review") setMode("ask");
  }

  async function refreshPendingCount() {
    if (state.role !== "admin") return;
    try {
      const pending = await api("/api/v1/admin/drafts?status=pending");
      el.reviewCount.textContent = pending.length;
      el.reviewCount.hidden = pending.length === 0;
      el.reviewTab.setAttribute("aria-label", `Review queue, ${pending.length} pending`);
    } catch { /* badge is best-effort */ }
  }

  function relativeTime(iso) {
    const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    return new Date(iso).toLocaleDateString();
  }

  function setReviewFilter(status) {
    state.reviewStatus = status;
    el.reviewFilter.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.status === status)));
    loadDrafts();
  }

  async function loadDrafts(selectId = null) {
    el.draftList.innerHTML = `<div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>`;
    el.draftPane.innerHTML = "";
    try {
      state.drafts = await api(`/api/v1/admin/drafts?status=${state.reviewStatus}`);
    } catch (error) {
      el.draftList.innerHTML = `<p class="warning">${icon("i-alert")}<span>${escapeHtml(error.message)}</span></p>`;
      return;
    }
    renderDraftList();
    const target = state.drafts.find((d) => d.id === selectId) || state.drafts[0];
    if (target) selectDraft(target.id);
    else renderEmptyPane();
  }

  function renderDraftList() {
    el.draftList.innerHTML = "";
    if (!state.drafts.length) {
      el.draftList.innerHTML = `<p class="muted" style="padding:8px 4px">No ${state.reviewStatus} drafts.</p>`;
      return;
    }
    state.drafts.forEach((draft) => {
      const item = node(`
        <button type="button" class="draft-item">
          <span class="draft-q"></span>
          <span class="draft-meta"><span class="asked">Asked ${draft.asked_count}×</span><span>${relativeTime(draft.updated_at)}</span></span>
        </button>`);
      item.querySelector(".draft-q").textContent = draft.question;
      item.dataset.id = draft.id;
      item.addEventListener("click", () => selectDraft(draft.id));
      el.draftList.appendChild(item);
    });
  }

  function renderEmptyPane() {
    const copy = {
      pending: ["Nothing to review", "When the documentation cannot answer a question, the general answer lands here so you can verify it before it becomes company documentation."],
      approved: ["No approved drafts yet", "Approved drafts are published to data/docs/approved/ and cited like any other document."],
      rejected: ["No rejected drafts", "Rejected drafts never reach the documentation."],
    }[state.reviewStatus];
    el.draftPane.innerHTML = `
      <div class="pane-empty"><div>
        ${icon("i-shield")}
        <p style="color:var(--color-foreground);font-weight:600;margin-top:12px">${copy[0]}</p>
        <p style="max-width:420px;margin:6px auto 0">${copy[1]}</p>
        ${state.reviewStatus === "pending" ? `<button type="button" class="btn btn-ghost" id="empty-to-chat">Back to chat</button>` : ""}
      </div></div>`;
    el.draftPane.querySelector("#empty-to-chat")?.addEventListener("click", () => setMode("ask"));
  }

  function selectDraft(id) {
    const draft = state.drafts.find((d) => d.id === id);
    if (!draft) return;
    state.selectedDraft = draft;
    el.draftList.querySelectorAll(".draft-item").forEach((i) => i.setAttribute("aria-current", String(i.dataset.id === id)));
    if (draft.status === "pending") renderEditor(draft);
    else renderRecord(draft);
  }

  function renderEditor(draft) {
    const typeOptions = Object.entries(DOC_TYPES)
      .map(([value, meta]) => `<option value="${value}">${meta.label}</option>`).join("");
    el.draftPane.innerHTML = `
      <form class="draft-form" novalidate>
        <div class="error-summary" tabindex="-1" hidden><h3>Fix these fields before continuing</h3><ul></ul></div>

        <div class="field">
          <span class="field-label">Asked by developers</span>
          <ol class="asked-list"></ol>
        </div>

        <div class="form-row">
          <div class="field">
            <label for="f-title">Title</label>
            <input id="f-title" maxlength="120" required aria-describedby="e-title">
            <p class="field-error" id="e-title"></p>
          </div>
          <div class="field">
            <label for="f-docid">Document ID</label>
            <input id="f-docid" class="mono" maxlength="60" required spellcheck="false" aria-describedby="h-docid e-docid">
            <p class="help" id="h-docid">Lowercase, numbers and dashes. Developers will see it as the citation <code>[doc_id]</code>.</p>
            <p class="field-error" id="e-docid"></p>
          </div>
        </div>

        <div class="form-row">
          <div class="field">
            <label for="f-type">Document type</label>
            <select id="f-type">${typeOptions}</select>
          </div>
          <div class="field">
            <label for="f-tags">Tags</label>
            <input id="f-tags" aria-describedby="h-tags">
            <p class="help" id="h-tags">Comma separated. They improve search.</p>
          </div>
        </div>

        <div class="field">
          <div class="content-tabs">
            <label for="f-content">Content (Markdown)</label>
            <div class="segmented" role="radiogroup" aria-label="Content view">
              <button type="button" role="radio" aria-checked="true" data-view="edit">Edit</button>
              <button type="button" role="radio" aria-checked="false" data-view="preview">Preview</button>
            </div>
          </div>
          <textarea id="f-content" required aria-describedby="h-content e-content"></textarea>
          <div class="preview markdown" hidden></div>
          <p class="help" id="h-content">Written by the model from general knowledge. Correct anything that differs from how your team works before publishing.</p>
          <p class="field-error" id="e-content"></p>
        </div>

        <div class="form-actions">
          <button type="button" class="btn btn-danger" data-action="reject">${icon("i-x")} Reject</button>
          <button type="button" class="btn btn-ghost" data-action="save">Save draft</button>
          <button type="submit" class="btn btn-primary">${icon("i-check")} Approve &amp; publish</button>
        </div>
      </form>`;

    const form = el.draftPane.querySelector("form");
    const askedList = form.querySelector(".asked-list");
    draft.questions.forEach((q) => { const li = document.createElement("li"); li.textContent = q; askedList.appendChild(li); });
    form.querySelector("#f-title").value = draft.title;
    form.querySelector("#f-docid").value = draft.doc_id;
    form.querySelector("#f-type").value = draft.doc_type;
    form.querySelector("#f-tags").value = (draft.tags || []).join(", ");
    form.querySelector("#f-content").value = draft.content;

    Object.keys(FIELD_RULES).forEach((name) => {
      form.querySelector(`#${FIELD_IDS[name]}`).addEventListener("blur", () => { validateField(form, name); refreshSummary(form); });
    });
    form.querySelectorAll(".content-tabs [data-view]").forEach((btn) => btn.addEventListener("click", () => toggleContentView(form, btn.dataset.view)));
    form.querySelector('[data-action="save"]').addEventListener("click", () => saveDraft(form, draft));
    form.querySelector('[data-action="reject"]').addEventListener("click", () => rejectDraft(form, draft));
    form.addEventListener("submit", (event) => { event.preventDefault(); approveDraft(form, draft); });
  }

  function toggleContentView(form, view) {
    const preview = form.querySelector(".preview");
    const textarea = form.querySelector("#f-content");
    form.querySelectorAll(".content-tabs [data-view]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.view === view)));
    if (view === "preview") renderMarkdown(preview, textarea.value);
    preview.hidden = view !== "preview";
    textarea.hidden = view === "preview";
  }

  function validateField(form, name) {
    const input = form.querySelector(`#${FIELD_IDS[name]}`);
    const message = FIELD_RULES[name](input.value);
    input.setAttribute("aria-invalid", String(Boolean(message)));
    form.querySelector(`#e-${name === "doc_id" ? "docid" : name}`).textContent = message;
    return message;
  }

  function refreshSummary(form) {
    // Keep a visible summary in sync as fields are fixed; never move focus here.
    const summary = form.querySelector(".error-summary");
    if (summary.hidden) return;
    const remaining = Object.keys(FIELD_RULES).filter((name) => FIELD_RULES[name](form.querySelector(`#${FIELD_IDS[name]}`).value));
    if (!remaining.length) summary.hidden = true;
    else summary.querySelectorAll("li").forEach((li) => {
      const id = li.querySelector("a").getAttribute("href").slice(1);
      li.hidden = !remaining.some((name) => FIELD_IDS[name] === id);
    });
  }

  function validateForm(form) {
    const errors = Object.keys(FIELD_RULES).map((name) => [name, validateField(form, name)]).filter(([, m]) => m);
    const summary = form.querySelector(".error-summary");
    summary.hidden = !errors.length;
    if (errors.length) {
      // The content textarea may be hidden behind the preview tab.
      if (errors.some(([name]) => name === "content")) toggleContentView(form, "edit");
      summary.querySelector("ul").innerHTML = errors
        .map(([name, message]) => `<li><a href="#${FIELD_IDS[name]}">${FIELD_LABELS[name]}: ${escapeHtml(message)}</a></li>`).join("");
      summary.querySelectorAll("a").forEach((a) => a.addEventListener("click", (event) => {
        event.preventDefault();
        form.querySelector(a.getAttribute("href")).focus();
      }));
      summary.focus();
    }
    return !errors.length;
  }

  function formPayload(form) {
    return {
      title: form.querySelector("#f-title").value.trim(),
      doc_id: form.querySelector("#f-docid").value.trim(),
      doc_type: form.querySelector("#f-type").value,
      tags: form.querySelector("#f-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
      content: form.querySelector("#f-content").value,
    };
  }

  function setFormBusy(form, busy) {
    form.querySelectorAll("button").forEach((b) => { b.disabled = busy; });
    el.draftPane.setAttribute("aria-busy", String(busy));
  }

  function showServerError(form, error) {
    if (error.status === 409 && /doc_id/i.test(error.message)) {
      form.querySelector("#f-docid").setAttribute("aria-invalid", "true");
      form.querySelector("#e-docid").textContent = error.message;
      form.querySelector("#f-docid").focus();
    } else {
      toast(error.message);
    }
  }

  async function saveDraft(form, draft) {
    if (!validateForm(form)) return;
    setFormBusy(form, true);
    try {
      const saved = await api(`/api/v1/admin/drafts/${draft.id}`, { method: "PATCH", body: JSON.stringify(formPayload(form)) });
      Object.assign(draft, saved);
      toast("Draft saved");
    } catch (error) {
      showServerError(form, error);
    } finally {
      setFormBusy(form, false);
    }
  }

  async function approveDraft(form, draft) {
    if (!validateForm(form)) return;
    const payload = formPayload(form);
    const { ok } = await confirmAction({
      title: "Publish to the company documentation?",
      message: `“${payload.title}” will be added as [${payload.doc_id}] and the index will be rebuilt. From then on developers get cited answers from it.`,
      okLabel: "Approve & publish",
    });
    if (!ok) return;
    setFormBusy(form, true);
    try {
      const { index } = await api(`/api/v1/admin/drafts/${draft.id}/approve`, { method: "POST", body: JSON.stringify(payload) });
      toast(`Published as [${payload.doc_id}] · ${index.documents} documents indexed`);
      await Promise.all([loadDocuments(), loadHealth(), refreshPendingCount()]);
      loadDrafts();
    } catch (error) {
      setFormBusy(form, false);
      showServerError(form, error);
    }
  }

  async function rejectDraft(form, draft) {
    const { ok, note } = await confirmAction({
      title: "Reject this draft?",
      message: "It will not be added to the documentation. It stays in the Rejected list for reference.",
      okLabel: "Reject draft",
      danger: true,
      withNote: true,
    });
    if (!ok) return;
    setFormBusy(form, true);
    try {
      await api(`/api/v1/admin/drafts/${draft.id}/reject`, { method: "POST", body: JSON.stringify({ note }) });
      toast("Draft rejected");
      await Promise.all([loadHealth(), refreshPendingCount()]);
      loadDrafts();
    } catch (error) {
      setFormBusy(form, false);
      toast(error.message);
    }
  }

  function renderRecord(draft) {
    const approved = draft.status === "approved";
    el.draftPane.innerHTML = `
      <div class="draft-form">
        <div class="msg-head">
          <h2 style="font-size:18px" class="record-title"></h2>
          <span class="badge ${approved ? "badge-answered" : "badge-error"}">${icon(approved ? "i-check" : "i-x")}${approved ? "Approved" : "Rejected"}</span>
        </div>
        <dl class="review-record">
          <dt>Question</dt><dd class="r-question"></dd>
          <dt>Asked</dt><dd>${draft.asked_count}×</dd>
          <dt>Reviewed by</dt><dd class="mono">${escapeHtml(draft.reviewed_by || "-")}</dd>
          <dt>Reviewed</dt><dd>${draft.reviewed_at ? escapeHtml(new Date(draft.reviewed_at).toLocaleString()) : "-"}</dd>
          ${approved
            ? `<dt>Published as</dt><dd><button type="button" class="cite">${escapeHtml(draft.doc_id)}</button> <span class="muted mono">${escapeHtml(draft.published_path || "")}</span></dd>`
            : `<dt>Reason</dt><dd class="r-note"></dd>`}
        </dl>
        <p class="section-label">Content</p>
        <div class="preview markdown"></div>
      </div>`;
    el.draftPane.querySelector(".record-title").textContent = draft.title;
    el.draftPane.querySelector(".r-question").textContent = draft.question;
    const note = el.draftPane.querySelector(".r-note");
    if (note) note.textContent = draft.review_note || "-";
    el.draftPane.querySelector(".cite")?.addEventListener("click", () => openDocument(draft.doc_id));
    renderMarkdown(el.draftPane.querySelector(".preview"), draft.content);
  }

  function confirmAction({ title, message, okLabel, danger = false, withNote = false }) {
    return new Promise((resolve) => {
      const form = $("#confirm-form");
      const ok = $("#confirm-ok");
      $("#confirm-title").textContent = title;
      $("#confirm-message").textContent = message;
      ok.textContent = okLabel;
      ok.className = `btn ${danger ? "btn-danger-solid" : "btn-primary"}`;
      $("#confirm-note-wrap").hidden = !withNote;
      $("#confirm-note").value = "";

      const finish = (result) => {
        form.onsubmit = null;
        $("#confirm-cancel").onclick = null;
        el.confirm.onclose = null;
        if (el.confirm.open) el.confirm.close();
        resolve(result);
      };
      form.onsubmit = (event) => { event.preventDefault(); finish({ ok: true, note: $("#confirm-note").value.trim() || null }); };
      $("#confirm-cancel").onclick = () => finish({ ok: false });
      el.confirm.onclose = () => finish({ ok: false });  // Esc
      el.confirm.showModal();
      (withNote ? $("#confirm-note") : ok).focus();
    });
  }

  // ---------------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------------

  el.form.addEventListener("submit", (event) => { event.preventDefault(); submit(); });
  el.input.addEventListener("input", autoSize);
  el.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submit();
    }
  });
  document.querySelectorAll(".mode-btn").forEach((btn) => btn.addEventListener("click", () => setMode(btn.dataset.mode)));
  $("#new-chat").addEventListener("click", newConversation);
  $("#open-settings").addEventListener("click", () => openSettings());
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#cancel-settings").addEventListener("click", () => el.settings.close());
  $("#close-drawer").addEventListener("click", closeDrawer);
  $("#open-sidebar").addEventListener("click", openSidebar);
  $("#close-sidebar").addEventListener("click", closeSidebar);
  el.scrim.addEventListener("click", closeSidebar);
  el.reviewFilter.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => setReviewFilter(btn.dataset.status)));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { closeDrawer(); closeSidebar(); }
  });

  renderSuggestions();
  renderScopeChips();
  loadHealth();
  if (state.apiKey) { loadDocuments(); loadMe(); }
  else openSettings();
})();
