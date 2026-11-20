"use strict";

const $ = (id) => document.getElementById(id);
function newConversationId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // Also support a local LAN address where randomUUID is unavailable.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
const CHAT_STORAGE_KEY = "sunoida.current-chat.v1";

function loadConversation() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(CHAT_STORAGE_KEY));
    if (saved && /^[0-9a-f-]{36}$/i.test(saved.sessionId) && Array.isArray(saved.messages)) {
      return { sessionId: saved.sessionId, selected: saved.selected || null, messages: saved.messages };
    }
  } catch { /* A storage restriction should not prevent chatting. */ }
  return { sessionId: newConversationId(), selected: null, messages: [] };
}

const state = { guides: [], controller: null, sequence: 0, viewer: null, ...loadConversation() };

function saveConversation() {
  try {
    const { sessionId, selected, messages } = state;
    sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify({ sessionId, selected, messages: messages.slice(-40) }));
  } catch { /* Chat can continue in the current page when storage is unavailable. */ }
}
const form = $("chat-form");
const input = $("message");
const send = $("send");
const log = $("messages");
const status = $("status");
const dialog = $("page-dialog");
const layoutBadge = document.querySelector(".version-pill");
if (layoutBadge) {
  layoutBadge.textContent = "LOCAL · CHAT MEMORY";
  layoutBadge.title = "LangChain remembers recent messages in this conversation. Screenshots come from the guides.";
}

function element(tag, className = "", text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("class", "icon");
  node.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  node.append(use);
  return node;
}

function guideUrl(id, suffix) {
  return `/api/guides/${encodeURIComponent(id)}/${suffix}`;
}

function localSourceUrl(value) {
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/guides/")) {
    throw new Error("The guide reference has an invalid address.");
  }
  return url.href;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw new Error("The backend returned an unreadable response."); }
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status}).`);
  }
  return data;
}

function updateComposer() {
  $("character-count").textContent = `${input.value.length} / 2000`;
  send.disabled = !state.controller && !input.value.trim();
  send.replaceChildren(icon(state.controller ? "stop" : "arrow"));
  send.setAttribute("aria-label", state.controller ? "Stop waiting for this answer" : "Send question");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
}

function scrollToLatest() {
  const container = $("conversation-scroll");
  container.scrollTop = container.scrollHeight;
}

function setDrawer(open) {
  $("sidebar").classList.toggle("open", open);
  $("sidebar").inert = window.innerWidth <= 700 && !open;
  $("drawer-backdrop").hidden = !open;
  $("menu-toggle").setAttribute("aria-expanded", String(open));
  if (!open) $("menu-toggle").focus({ preventScroll: true });
}

function syncNavigation() {
  const mobile = window.innerWidth <= 700;
  $("sidebar").inert = mobile && !$("sidebar").classList.contains("open");
  if (!mobile) {
    $("drawer-backdrop").hidden = true;
    $("sidebar").classList.remove("open");
    $("menu-toggle").setAttribute("aria-expanded", "false");
  }
}

function setScope(id) {
  if (state.selected !== id) {
    state.sessionId = newConversationId();
    if (state.controller) {
      state.sequence++;
      state.controller.abort();
      state.controller = null;
      updateComposer();
    }
    status.textContent = "Guide selection changed. Conversation memory starts fresh for this selection.";
  }
  state.selected = id;
  saveConversation();
  const guide = state.guides.find((item) => item.id === id);
  $("scope-label").textContent = guide ? guide.title : "All product guides";
  $("clear-scope").hidden = !guide;
  $("all-guides").classList.toggle("active", !guide);
  $("all-guides").setAttribute("aria-pressed", String(!guide));
  document.querySelectorAll(".guide-row").forEach((row) => {
    const selected = row.dataset.id === id;
    row.classList.toggle("active", selected);
    row.querySelector(".guide-select").setAttribute("aria-pressed", String(selected));
  });
  input.placeholder = guide ? `Ask about ${guide.title}…` : "Ask anything about your Sunoida guides…";
  if (window.innerWidth <= 700) setDrawer(false);
}

function showLibrary() {
  const list = $("guide-list");
  list.replaceChildren();
  $("guide-count").textContent = state.guides.length;
  if (!state.guides.length) {
    list.append(element("p", "library-loading", "Add your PDFs to backend/docs, then refresh this page."));
    return;
  }
  for (const guide of state.guides) {
    const row = element("div", "guide-row");
    row.dataset.id = guide.id;
    const select = element("button", "guide-select");
    select.type = "button";
    select.disabled = !guide.available;
    select.setAttribute("aria-pressed", "false");
    select.setAttribute("aria-label", `Search ${guide.title}`);
    const name = element("span", "guide-title", guide.title.replace(/^Vision /, ""));
    name.append(element("span", "guide-pages", guide.available ? `${guide.pages} pages` : "PDF needs attention"));
    select.append(element("span", "guide-badge", guide.short), name);
    select.addEventListener("click", () => setScope(state.selected === guide.id ? null : guide.id));
    const browse = element("button", "guide-browse");
    browse.type = "button";
    browse.disabled = !guide.available;
    browse.setAttribute("aria-label", `Browse ${guide.title}`);
    browse.title = `Browse ${guide.title}`;
    browse.append(icon("external"));
    browse.addEventListener("click", () => openGuide(guide));
    row.append(select, browse);
    list.append(row);
  }

  const featured = state.guides.find((item) => item.short === "API" && item.available)
    || state.guides.find((item) => item.available);
  if (featured) {
    const page = featured.short === "API" ? Math.min(5, featured.pages) : 1;
    $("feature-title").textContent = featured.title;
    $("feature-page").textContent = `Page ${page}`;
    $("feature-image").alt = `Screenshot from ${featured.title}`;
    $("feature-image").addEventListener("error", () => { $("guide-feature").hidden = true; }, { once: true });
    requestJson(guideUrl(featured.id, `pages/${page}/figures`)).then((data) => {
      const figure = data.figures?.[0];
      if (!figure) return;
      $("feature-image").src = localSourceUrl(figure.image_url);
      $("feature-preview").onclick = () => openSource({ document_id: featured.id, title: featured.title,
        page, page_count: featured.pages, figure_id: figure.figure_id, preview_url: figure.image_url });
      $("guide-feature").hidden = false;
    }).catch(() => { $("guide-feature").hidden = true; });
  }
}

function makeUserMessage(text) {
  $("welcome").hidden = true;
  const article = element("article", "message message-user");
  article.append(element("div", "user-content", text));
  log.append(article);
  return article;
}

// Build supported formatting with DOM nodes. Model text is never inserted as HTML.
function inlineText(parent, text, sources, onCitation = () => {}) {
  const tokens = /(\[\d+\]|\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
  let position = 0;
  for (const match of text.matchAll(tokens)) {
    parent.append(document.createTextNode(text.slice(position, match.index)));
    const token = match[0];
    if (/^\[\d+\]$/.test(token)) {
      const source = sources.find((item) => item.index === Number(token.slice(1, -1)));
      if (source) {
        const button = element("button", "citation", source.index);
        button.type = "button";
        button.setAttribute("aria-label", `View reference ${source.index}: ${source.title}, page ${source.page}`);
        button.addEventListener("click", () => openSource(source));
        parent.append(button);
        onCitation(source);
      } else parent.append(document.createTextNode(token));
    } else if (token.startsWith("**")) {
      const strong = element("strong");
      inlineText(strong, token.slice(2, -2), sources, onCitation);
      parent.append(strong);
    }
    else parent.append(element("code", "", token.slice(1, -1)));
    position = match.index + token.length;
  }
  parent.append(document.createTextNode(text.slice(position)));
}

function sourceKey(source) {
  return source.figure_id ? `figure:${source.figure_id}` : `${source.document_id}:${source.page}`;
}

function inlineGuide(source) {
  const figure = element("figure", "inline-guide");
  figure.dataset.sourceKey = sourceKey(source);
  const preview = element("button", "inline-guide-preview");
  preview.type = "button";
  preview.setAttribute("aria-label", `Enlarge screenshot from ${source.title}, page ${source.page}`);
  const image = element("img");
  image.loading = "lazy";
  image.decoding = "async";
  image.alt = `Screenshot extracted from ${source.title}, PDF page ${source.page}`;
  if (source.image_available !== false) image.src = localSourceUrl(source.preview_url || source.image_url);
  image.addEventListener("error", () => {
    image.remove();
    preview.classList.add("inline-guide-unavailable");
    preview.append(element("span", "image-unavailable", "Screenshot unavailable. Use Open PDF below."));
  }, { once: true });
  const zoom = element("span", "inline-guide-zoom", "Enlarge image");
  zoom.prepend(icon("external"));
  if (source.image_available === false) {
    preview.classList.add("inline-guide-unavailable");
    preview.append(element("span", "image-unavailable", "Page image unavailable. Use Open PDF below."));
  } else preview.append(image, zoom);
  preview.addEventListener("click", () => openSource(source));
  const caption = element("figcaption", "inline-guide-caption");
  const label = element("span", "inline-guide-label", source.title);
  label.append(element("span", "inline-guide-page", `Screenshot · PDF page ${source.page}`));
  const pdf = element("a", "inline-guide-pdf", "Open PDF");
  pdf.href = localSourceUrl(source.pdf_url);
  pdf.target = "_blank";
  pdf.rel = "noopener";
  pdf.append(icon("external"));
  caption.append(label, pdf);
  figure.append(preview, caption);
  return figure;
}

function pointPageSources(section, sources) {
  if (!Array.isArray(section.pages)) return [];
  return section.pages.flatMap((page) => {
    if (!page || typeof page !== "object" || page.show_image === false) return [];
    const source = sources.find((item) => item.index === page.index && item.document_id === page.document_id && item.page === page.page);
    if (!source) return [];
    if (!Array.isArray(page.figures)) return [];
    return page.figures.flatMap((figure) => {
      if (!figure || figure.show_image === false || !/^[a-f0-9]{32}$/.test(figure.figure_id)) return [];
      const expected = `/api/guides/${source.document_id}/pages/${source.page}/figures/${figure.figure_id}`;
      if (figure.image_url !== expected) return [];
      return [{ ...source, figure_id: figure.figure_id, image_available: true,
        preview_url: figure.image_url, image_url: figure.image_url }];
    });
  });
}

function renderAnswer(text, sources, answerBlocks, displayedSources = new Set()) {
  const body = element("div", "answer-body");
  let allowedImageKeys = null;
  function appendImages(parent, cited) {
    for (const source of cited) {
      const key = sourceKey(source);
      if (!source.figure_id || displayedSources.size >= 4 || displayedSources.has(key) || (allowedImageKeys && !allowedImageKeys.has(key))) continue;
      parent.append(inlineGuide(source));
      displayedSources.add(key);
    }
  }
  const sections = Array.isArray(answerBlocks) && answerBlocks.length && answerBlocks.every((block) => block && typeof block.text === "string" && Array.isArray(block.source_indices))
    ? answerBlocks : [{ text, source_indices: [] }];
  for (const section of sections) {
  let related = pointPageSources(section, sources);
  // Citations keep their links, but only the selected point displays a page.
  allowedImageKeys = Array.isArray(section.pages) ? new Set(related.map(sourceKey)) : null;
  const parts = section.text.split(/(```[\s\S]*?```)/g);
  for (const part of parts) {
    if (part.startsWith("```")) {
      const pre = element("pre");
      pre.append(element("code", "", part.replace(/^```[^\n]*\n?/, "").replace(/```$/, "")));
      body.append(pre);
      continue;
    }
    for (const block of part.split(/\n\s*\n/).filter((value) => value.trim())) {
      const lines = block.trim().split("\n");
      const listKind = lines.every((line) => /^\s*[-*]\s+/.test(line)) ? "ul"
        : lines.every((line) => /^\s*\d+[.)]\s+/.test(line)) ? "ol" : null;
      if (listKind) {
        const list = element(listKind);
        if (listKind === "ol") list.start = Number(lines[0].match(/^\s*(\d+)/)[1]);
        for (const line of lines) {
          const item = element("li");
          const cited = related;
          related = [];
          const itemText = element("span", "answer-step-text");
          inlineText(itemText, line.replace(/^\s*(?:[-*]|\d+[.)])\s+/, ""), sources, (source) => cited.push(source));
          item.append(itemText);
          appendImages(item, cited);
          list.append(item);
        }
        body.append(list);
      } else if (lines.length === 1 && /^#{1,4}\s/.test(block)) {
        const heading = element("h3");
        const cited = related;
        related = [];
        inlineText(heading, block.replace(/^#{1,4}\s+/, ""), sources, (source) => cited.push(source));
        body.append(heading);
        appendImages(body, cited);
      } else {
        const paragraph = element("p");
        const cited = related;
        related = [];
        lines.forEach((line, index) => {
          if (index) paragraph.append(document.createElement("br"));
          inlineText(paragraph, line, sources, (source) => cited.push(source));
        });
        body.append(paragraph);
        appendImages(body, cited);
      }
    }
  }
  }
  return { body, displayedSources };
}

function planPointImages(points, sources) {
  const anchors = new Map();
  points.forEach((point, position) => {
    const text = (point.original_text || point.text).trim();
    const priority = /^\d+[.)]\s/.test(text) ? 0 : /^[-*]\s/.test(text) ? 1 : 2;
    const indices = Array.isArray(point.source_indices) ? point.source_indices : [];
    for (const source of pointPageSources({ ...point, source_indices: indices }, sources)) {
      const key = sourceKey(source);
      const current = anchors.get(key);
      if (!current || priority < current.priority) anchors.set(key, { position, priority });
    }
  });
  return points.map((point, position) => {
    if (!Array.isArray(point.pages)) return point;
    return { ...point, pages: point.pages.map((page) => page && typeof page === "object"
      ? { ...page, figures: Array.isArray(page.figures) ? page.figures.map((figure) => figure && typeof figure === "object" ? ({ ...figure,
          show_image: figure.show_image !== false && anchors.get(sourceKey(figure))?.position === position }) : figure) : [] }
      : page) };
  });
}

function renderPointAnswer(points, sources) {
  const body = element("div", "answer-body answer-points");
  const displayedSources = new Set();
  for (const [position, point] of planPointImages(points, sources).entries()) {
    const indices = Array.isArray(point.source_indices) ? point.source_indices
      : (Array.isArray(point.pages) ? point.pages.map((page) => page.index) : []);
    const rendered = renderAnswer(point.text, sources, [{ ...point, source_indices: indices }], displayedSources);
    const section = element("section", "answer-point");
    section.dataset.pointPosition = String(position + 1);
    section.append(rendered.body);
    body.append(section);
  }
  return { body, displayedSources };
}

function sourceCard(source) {
  const card = element("article", "source-card");
  const thumbnail = element("button", "source-thumb");
  thumbnail.type = "button";
  thumbnail.setAttribute("aria-label", `Enlarge ${source.title}, page ${source.page}`);
  const image = element("img");
  image.loading = "lazy";
  image.alt = `Original ${source.title} guide, PDF page ${source.page}`;
  image.src = localSourceUrl(source.image_url);
  image.addEventListener("error", () => {
    image.remove();
    thumbnail.append(element("span", "image-unavailable", "Preview unavailable. Open the PDF below."));
  }, { once: true });
  const enlarge = element("span", "enlarge-icon");
  enlarge.append(icon("external"));
  thumbnail.append(image, element("span", "source-number", `[${source.index}]`), enlarge);
  thumbnail.addEventListener("click", () => openSource(source));
  const info = element("div", "source-info");
  const title = element("button", "source-title", source.title);
  title.type = "button";
  title.addEventListener("click", () => openSource(source));
  const meta = element("div", "source-meta");
  const link = element("a", "", "Open PDF");
  link.href = localSourceUrl(source.pdf_url);
  link.target = "_blank";
  link.rel = "noopener";
  link.append(icon("external"));
  meta.append(element("span", "", `PDF page ${source.page}`), link);
  info.append(title, meta);
  card.append(thumbnail, info);
  return card;
}

function makeAssistantMessage(data) {
  const sources = Array.isArray(data.sources) ? data.sources : [];
  const article = element("article", "message message-assistant");
  const heading = element("div", "assistant-heading");
  heading.append(element("span", "assistant-avatar", "s"), element("span", "", "Sunoida Assistant"));
  if (data.used_history === true) {
    heading.append(element("span", "conversation-context", "Used earlier messages"));
  }
  const points = Array.isArray(data.points) && data.points.length && data.points.every((point) => point && typeof point.text === "string") ? data.points : null;
  const rendered = points ? renderPointAnswer(points, sources) : renderAnswer(data.reply, sources, data.answer_blocks);
  article.append(heading, rendered.body);
  if (sources.length) {
    const extra = element("details", "additional-sources");
    const label = element("summary", "sources-header");
    label.append(icon("book"), document.createTextNode("Guide references"));
    const links = element("div", "guide-reference-links");
    const seen = new Set();
    for (const source of sources) {
      const key = `${source.document_id}:${source.page}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const link = element("a", "inline-guide-pdf", `${source.title} · PDF page ${source.page}`);
      link.href = localSourceUrl(source.pdf_url);
      link.target = "_blank";
      link.rel = "noopener";
      links.append(link);
    }
    extra.append(label, links);
    article.append(extra);
  }
  if (sources.length) {
    article.append(element("p", "source-notice", "Screenshots are extracted from the guides where available. Check the guide references for context."));
  }
  const suggestion = data.suggested_follow_up;
  if (typeof suggestion?.prompt === "string" && typeof suggestion?.question === "string") {
    const followUp = element("button", "follow-up-question", suggestion.prompt);
    followUp.type = "button";
    followUp.addEventListener("click", () => submitQuestion(suggestion.question));
    article.append(followUp);
  }
  const actions = element("div", "answer-actions");
  const copy = element("button", "copy-answer");
  copy.type = "button";
  copy.append(icon("copy"), document.createTextNode("Copy answer"));
  copy.addEventListener("click", async () => {
    try {
      const references = sources.map((source) => `[${source.index}] ${source.filename}, PDF page ${source.page}`).join("\n");
      await navigator.clipboard.writeText(data.reply + (references ? `\n\nRetrieved references:\n${references}` : ""));
      copy.replaceChildren(icon("check"), document.createTextNode("Copied"));
      setTimeout(() => copy.replaceChildren(icon("copy"), document.createTextNode("Copy answer")), 1800);
    } catch { status.textContent = "Copy is unavailable in this browser. You can select the answer text instead."; }
  });
  actions.append(copy);
  article.append(actions);
  log.append(article);
  return article;
}

async function submitQuestion(question) {
  const message = question.trim();
  if (!message || state.controller) return;
  if (message.length > 2000) { status.textContent = "Please keep your question within 2,000 characters."; return; }
  const sequence = ++state.sequence;
  const controller = new AbortController();
  state.controller = controller;
  status.textContent = "";
  input.value = "";
  updateComposer();
  makeUserMessage(message);
  state.messages.push({ role: "You", text: message });
  $("export-chat").disabled = false;
  const pending = element("div", "pending");
  const dots = element("span", "pending-dots");
  dots.setAttribute("aria-hidden", "true");
  dots.append(element("i"), element("i"), element("i"));
  pending.append(dots, document.createTextNode("Looking through your guides and preparing an answer…"));
  log.append(pending);
  scrollToLatest();
  const timer = setTimeout(() => controller.abort("timeout"), 360000);
  let answerArticle = null;
  try {
    const data = await requestJson("/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, source_id: state.selected, session_id: state.sessionId }), signal: controller.signal,
    });
    if (sequence !== state.sequence) return;
    if (typeof data.reply !== "string") throw new Error("The backend response is missing its reply.");
    answerArticle = makeAssistantMessage(data);
    const references = (data.sources || []).map((source) => `[${source.index}] ${source.filename}, PDF page ${source.page}`).join("\n");
    state.messages.push({ role: "Sunoida Assistant", data, text: data.reply + (references ? "\n\nRetrieved references:\n" + references : "") });
    saveConversation();
  } catch (error) {
    if (sequence !== state.sequence) return;
    // A stopped request may still complete on the server. Do not remember an
    // unseen answer in the next question's conversation.
    state.sessionId = newConversationId();
    saveConversation();
    const text = controller.signal.aborted
      ? (controller.signal.reason === "timeout" ? "This answer took too long. Try a shorter question or check Ollama." : "Stopped waiting for this answer. Ollama may still finish the request in the background.")
      : error.message;
    log.append(element("div", "message message-error", text));
    status.textContent = "Conversation memory has been reset. Please name the product and topic in your next question.";
  } finally {
    clearTimeout(timer);
    pending.remove();
    if (sequence === state.sequence) {
      state.controller = null;
      updateComposer();
      input.focus({ preventScroll: true });
      if (answerArticle) {
        const container = $("conversation-scroll");
        container.scrollTop += answerArticle.getBoundingClientRect().top - container.getBoundingClientRect().top - 16;
      } else scrollToLatest();
    }
  }
}

function openGuide(guide, page = 1) {
  state.viewer = { id: guide.id, title: guide.title, page, count: guide.pages };
  displayPage();
  if (!dialog.open) dialog.showModal();
}

function openSource(source) {
  state.viewer = { id: source.document_id, title: source.title, page: source.page, count: source.page_count,
    figure: source.figure_id ? source.preview_url : null };
  displayPage();
  if (!dialog.open) dialog.showModal();
}

function displayPage() {
  const viewer = state.viewer;
  const image = $("page-image");
  $("preview-title").textContent = viewer.title;
  $("preview-kind").textContent = viewer.figure ? "GUIDE SCREENSHOT" : "ORIGINAL GUIDE PAGE";
  $("page-position").textContent = `Page ${viewer.page} of ${viewer.count}`;
  $("previous-page").disabled = Boolean(viewer.figure) || viewer.page <= 1;
  $("next-page").disabled = Boolean(viewer.figure) || viewer.page >= viewer.count;
  $("open-pdf").href = guideUrl(viewer.id, `pdf#page=${viewer.page}`);
  image.hidden = true;
  $("preview-status").hidden = false;
  $("preview-status").textContent = viewer.figure ? "Loading screenshot…" : "Loading the original guide page…";
  image.onload = () => { image.hidden = false; $("preview-status").hidden = true; };
  image.onerror = () => { image.hidden = true; $("preview-status").textContent = "This page preview could not load. Use Open PDF to view the original document."; };
  image.alt = `${viewer.title}, PDF page ${viewer.page}`;
  image.src = viewer.figure ? localSourceUrl(viewer.figure) : guideUrl(viewer.id, `pages/${viewer.page}/preview?size=full`);
  $("preview-scroll").scrollTop = 0;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.controller) state.controller.abort();
  else submitQuestion(input.value);
});
// A stop button must remain usable even when the cleared textarea is empty.
send.addEventListener("click", (event) => {
  if (state.controller) { event.preventDefault(); state.controller.abort(); }
});
input.addEventListener("input", updateComposer);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!state.controller) submitQuestion(input.value);
  }
});
document.querySelectorAll(".starter").forEach((button) => button.addEventListener("click", () => {
  setScope(null);
  submitQuestion(button.dataset.question);
}));
$("all-guides").addEventListener("click", () => setScope(null));
$("clear-scope").addEventListener("click", () => setScope(null));
$("menu-toggle").addEventListener("click", () => setDrawer(!$("sidebar").classList.contains("open")));
$("drawer-backdrop").addEventListener("click", () => setDrawer(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("sidebar").classList.contains("open")) setDrawer(false);
});
$("new-chat").addEventListener("click", () => {
  state.sequence++;
  if (state.controller) state.controller.abort();
  state.controller = null;
  state.messages = [];
  state.sessionId = newConversationId();
  saveConversation();
  log.replaceChildren();
  $("welcome").hidden = false;
  $("export-chat").disabled = true;
  input.value = "";
  status.textContent = "";
  updateComposer();
  if (window.innerWidth <= 700) setDrawer(false);
  input.focus();
  $("conversation-scroll").scrollTop = 0;
});
$("export-chat").addEventListener("click", () => {
  const text = "Sunoida Guide Assistant\n\n" + state.messages.map((message) => `${message.role}\n${message.text}`).join("\n\n---\n\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = element("a");
  link.href = url;
  link.download = "sunoida-conversation.txt";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("close-preview").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  const box = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
});
$("previous-page").addEventListener("click", () => { if (state.viewer.page > 1) { state.viewer.page--; displayPage(); } });
$("next-page").addEventListener("click", () => { if (state.viewer.page < state.viewer.count) { state.viewer.page++; displayPage(); } });

window.addEventListener("resize", syncNavigation);
syncNavigation();
updateComposer();
for (const message of state.messages) {
  if (message.role === "You") makeUserMessage(message.text);
  else if (message.data) makeAssistantMessage(message.data);
}
if (state.messages.length) {
  $("export-chat").disabled = false;
  scrollToLatest();
}
requestJson("/api/guides").then((data) => {
  state.guides = data.guides || [];
  showLibrary();
  if (state.selected) setScope(state.guides.some((guide) => guide.id === state.selected) ? state.selected : null);
}).catch((error) => {
  $("guide-list").replaceChildren(element("p", "library-loading", "Could not load guides. Check that the updated backend is running."));
  status.textContent = error.message;
});
