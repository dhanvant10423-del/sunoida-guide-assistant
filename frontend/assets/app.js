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
const HISTORY_STORAGE_KEY = "sunoida.chat-history.v1";

function blankConversation() {
  const id = newConversationId();
  return { chatId: id, sessionId: id, selected: null, title: "", messages: [] };
}

function loadConversation() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(CHAT_STORAGE_KEY));
    if (saved && /^[0-9a-f-]{36}$/i.test(saved.sessionId) && Array.isArray(saved.messages)) {
      return {
        chatId: saved.chatId || saved.sessionId,
        sessionId: saved.sessionId,
        selected: saved.selected || null,
        title: saved.title || saved.messages.find((message) => message.role === "You")?.text || "",
        messages: saved.messages,
      };
    }
  } catch { /* A storage restriction should not prevent chatting. */ }
  return blankConversation();
}

function loadHistory(fallback = { chats: [], deleted: [] }) {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY));
    if (!saved) return fallback;
    const chats = Array.isArray(saved) ? saved : saved.chats;
    const deleted = Array.isArray(saved.deleted) ? saved.deleted : [];
    if (!Array.isArray(chats)) return fallback;
    return {
      chats: chats.filter((chat) => chat?.chatId && Array.isArray(chat.messages) && !deleted.includes(chat.chatId)),
      deleted,
    };
  } catch {
    return fallback;
  }
}

const history = loadHistory();
const previousChat = loadConversation();
const activeChat = history.deleted.includes(previousChat.chatId)
  ? blankConversation()
  : history.chats.find((chat) => chat.chatId === previousChat.chatId) || previousChat;
const state = {
  guides: [], history, controller: null, sequence: 0, viewer: null, toolChatId: null,
  ...activeChat, messages: [...activeChat.messages],
};

function writeHistory(history, prune = false) {
  const chats = [...history.chats];
  while (true) {
    try {
      localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify({ ...history, chats }));
      state.history = { ...history, chats };
      return true;
    } catch (error) {
      const oldest = chats.findLastIndex((chat) => !chat.pinned && chat.chatId !== state.chatId);
      if (!prune || error.name !== "QuotaExceededError" || oldest < 0) return false;
      chats.splice(oldest, 1);
    }
  }
}

function saveConversation(archive = true) {
  const { chatId, sessionId, selected, messages } = state;
  const latest = loadHistory(state.history);
  if (latest.deleted.includes(chatId)) {
    state.history = latest;
    activateChat(blankConversation(), false);
    return false;
  }
  const saved = latest.chats.find((chat) => chat.chatId === chatId);
  const title = saved?.title || state.title;
  state.title = title;
  const snapshot = { chatId, sessionId, selected, title, pinned: Boolean(saved?.pinned), messages: messages.slice(-40) };
  try {
    sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(snapshot));
  } catch { /* Chat can continue in the current page when storage is unavailable. */ }
  if (archive && messages.length) {
    const chats = [snapshot, ...latest.chats.filter((chat) => chat.chatId !== chatId)];
    let recent = 0;
    const next = { ...latest, chats: chats.filter((chat) => chat.pinned || recent++ < 30) };
    if (!writeHistory(next, true)) {
      state.history = next;
      $("history-status").textContent = "Browser storage is unavailable. Recent changes may be lost when you close this tab.";
    }
  }
  showHistory();
  return true;
}
const form = $("chat-form");
const input = $("message");
const send = $("send");
const log = $("messages");
const status = $("status");
const dialog = $("page-dialog");
const guideSelect = $("guide-select");
const historyList = $("chat-history");
const chatTools = $("chat-tools");

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
  guideSelect.disabled = Boolean(state.controller) || !state.guides.some((guide) => guide.available);
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
  if (open) $("close-history").focus({ preventScroll: true });
  else $("menu-toggle").focus({ preventScroll: true });
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

function updateGuidePicker() {
  const guide = state.guides.find((item) => item.id === state.selected && item.available);
  guideSelect.value = guide?.id || "";
  $("open-guide").hidden = !guide;
  input.placeholder = guide ? "Ask about " + guide.title + "…" : "Ask anything about your Sunoida guides…";
}

function loadGuidePicker(guides) {
  state.guides = guides;
  const allGuides = element("option", "", "All product guides");
  allGuides.value = "";
  guideSelect.replaceChildren(allGuides);
  for (const guide of guides) {
    const option = element("option", "", guide.title + (guide.available ? "" : " (unavailable)"));
    option.value = guide.id;
    option.disabled = !guide.available;
    guideSelect.append(option);
  }
  if (state.selected && !guides.some((guide) => guide.id === state.selected && guide.available)) {
    setScope(null);
  }
  updateGuidePicker();
  guideSelect.disabled = Boolean(state.controller) || !guides.some((guide) => guide.available);
}

function setScope(id) {
  if (id === state.selected || state.controller) return;
  if (state.messages.length) {
    state.sessionId = newConversationId();
    status.textContent = "Guide changed. The next question starts with fresh context.";
  }
  state.selected = id;
  updateGuidePicker();
  saveConversation();
}

function showHistory() {
  historyList.replaceChildren();
  const query = $("chat-search").value.trim().toLowerCase();
  const matches = state.history.chats.filter((chat) => {
    return !query || chat.title?.toLowerCase().includes(query) ||
      chat.messages.some((message) => message.text?.toLowerCase().includes(query));
  });
  if (!matches.length) {
    historyList.append(element("p", "history-empty", query ? "No matching chats" : "No previous chats yet"));
    return;
  }
  const ordered = [...matches].sort((first, second) => Number(Boolean(second.pinned)) - Number(Boolean(first.pinned)));
  for (const chat of ordered) {
    const title = chat.title || "Untitled chat";
    const row = element("div", "history-row");
    const button = element("button", "history-chat");
    button.type = "button";
    button.title = title;
    if (chat.pinned) {
      button.append(icon("pin"));
      button.setAttribute("aria-label", title + ", pinned");
    }
    button.append(element("span", "history-title", title));
    if (chat.chatId === state.chatId) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => {
      if (chat.chatId !== state.chatId) activateChat(chat);
      else if (window.innerWidth <= 700) setDrawer(false);
    });
    const options = element("button", "icon-button history-options");
    options.type = "button";
    options.title = "Chat options";
    options.dataset.chatId = chat.chatId;
    options.setAttribute("aria-label", "Options for " + title);
    options.setAttribute("aria-haspopup", "dialog");
    options.append(icon("more"));
    options.addEventListener("click", () => openChatTools(chat.chatId));
    row.append(button, options);
    historyList.append(row);
  }
}

function selectedSavedChat() {
  return loadHistory(state.history).chats.find((chat) => chat.chatId === state.toolChatId);
}

function showChatTool(panel) {
  for (const id of ["chat-tools-actions", "chat-rename-form", "chat-share-panel", "chat-delete-panel"]) {
    $(id).hidden = id !== panel;
  }
  $("chat-tools-status").textContent = "";
}

function openChatTools(chatId) {
  state.toolChatId = chatId;
  const chat = selectedSavedChat();
  if (!chat) return;
  $("chat-tools-name").textContent = chat.title || "Untitled chat";
  $("pin-chat").textContent = chat.pinned ? "Unpin chat" : "Pin chat";
  showChatTool("chat-tools-actions");
  chatTools.showModal();
}

function updateSavedChat(changes) {
  const latest = loadHistory(state.history);
  const chat = latest.chats.find((item) => item.chatId === state.toolChatId);
  if (!chat) return false;
  const updated = { ...chat, ...changes };
  if (!writeHistory({ ...latest, chats: latest.chats.map((item) => item === chat ? updated : item) })) {
    $("chat-tools-status").textContent = "Could not save the change in this browser.";
    return false;
  }
  if (chat.chatId === state.chatId) {
    state.title = updated.title;
    saveConversation(false);
  } else {
    showHistory();
  }
  return true;
}

function deleteSavedChat() {
  const latest = loadHistory(state.history);
  const id = state.toolChatId;
  const next = {
    chats: latest.chats.filter((chat) => chat.chatId !== id),
    deleted: [...new Set([...latest.deleted, id])],
  };
  if (!writeHistory(next)) {
    $("chat-tools-status").textContent = "Could not delete this chat from browser storage.";
    return;
  }
  chatTools.close();
  if (id === state.chatId) activateChat(blankConversation(), false);
  else showHistory();
  $("history-status").textContent = "Chat deleted.";
}

function transcriptText(chat) {
  const title = chat.title || "Sunoida Guide Assistant";
  return title + "\n\n" + chat.messages.map((message) => message.role + "\n" + message.text).join("\n\n---\n\n");
}

function downloadTranscript(chat) {
  const url = URL.createObjectURL(new Blob([transcriptText(chat)], { type: "text/plain;charset=utf-8" }));
  const link = element("a");
  link.href = url;
  link.download = "sunoida-conversation.txt";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderConversation() {
  log.replaceChildren();
  for (const message of state.messages) {
    if (message.role === "You") makeUserMessage(message.text);
    else if (message.data) makeAssistantMessage(message.data);
  }
  $("export-chat").disabled = !state.messages.length;
  updateComposer();
  scrollToLatest();
}

function activateChat(chat, preservePending = true) {
  if (state.controller) {
    state.sequence++;
    state.controller.abort();
    state.controller = null;
    // A suspended server request can complete after leaving the chat.
    state.sessionId = newConversationId();
    if (preservePending) saveConversation();
  }
  const { chatId, sessionId, selected, title, messages } = chat;
  Object.assign(state, { chatId, sessionId, selected, title, messages: [...messages] });
  if (state.guides.length && selected && !state.guides.some((guide) => guide.id === selected && guide.available)) {
    state.selected = null;
    state.sessionId = newConversationId();
    saveConversation();
  } else {
    saveConversation(false);
  }
  input.value = "";
  status.textContent = "";
  updateGuidePicker();
  renderConversation();
  if (window.innerWidth <= 700) setDrawer(false);
  input.focus({ preventScroll: true });
}

function makeUserMessage(text) {
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
  makeUserMessage(message);
  state.messages.push({ role: "You", text: message });
  state.title ||= message.replace(/\s+/g, " ").slice(0, 120);
  if (!saveConversation()) return;
  updateComposer();
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
guideSelect.addEventListener("change", () => setScope(guideSelect.value || null));
$("open-guide").addEventListener("click", () => {
  const guide = state.guides.find((item) => item.id === state.selected && item.available);
  if (guide) openGuide(guide);
});
$("menu-toggle").addEventListener("click", () => setDrawer(!$("sidebar").classList.contains("open")));
$("close-history").addEventListener("click", () => setDrawer(false));
$("drawer-backdrop").addEventListener("click", () => setDrawer(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("sidebar").classList.contains("open")) setDrawer(false);
});
$("new-chat").addEventListener("click", () => activateChat(blankConversation()));
$("export-chat").addEventListener("click", () => downloadTranscript(state));
$("chat-search").addEventListener("input", showHistory);
$("close-chat-tools").addEventListener("click", () => chatTools.close());
chatTools.addEventListener("close", () => {
  const id = state.toolChatId;
  state.toolChatId = null;
  $("chat-share-text").value = "";
  const trigger = Array.from(historyList.querySelectorAll(".history-options")).find((button) => button.dataset.chatId === id);
  if (trigger && !$("sidebar").inert) trigger.focus();
});
document.querySelectorAll(".chat-tool-back").forEach((button) => {
  button.addEventListener("click", () => {
    showChatTool("chat-tools-actions");
    $("pin-chat").focus();
  });
});
$("pin-chat").addEventListener("click", () => {
  const chat = selectedSavedChat();
  if (chat && updateSavedChat({ pinned: !chat.pinned })) {
    chatTools.close();
    $("history-status").textContent = chat.pinned ? "Chat unpinned." : "Chat pinned.";
  }
});
$("rename-chat").addEventListener("click", () => {
  showChatTool("chat-rename-form");
  const field = $("chat-name");
  field.value = selectedSavedChat()?.title || "";
  field.focus();
  field.select();
});
$("chat-rename-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const title = $("chat-name").value.trim();
  if (!title) {
    $("chat-tools-status").textContent = "Enter a chat title.";
    return;
  }
  if (updateSavedChat({ title })) chatTools.close();
});
$("share-chat").addEventListener("click", () => {
  const chat = selectedSavedChat();
  if (!chat) return;
  showChatTool("chat-share-panel");
  $("chat-share-text").value = transcriptText(chat);
  $("share-native").hidden = typeof navigator.share !== "function";
  $("copy-chat").focus();
});
$("copy-chat").addEventListener("click", async () => {
  const text = $("chat-share-text");
  try {
    await navigator.clipboard.writeText(text.value);
    $("chat-tools-status").textContent = "Transcript copied.";
  } catch {
    text.focus();
    text.select();
    $("chat-tools-status").textContent = "Use your browser’s Copy command to copy the selected transcript.";
  }
});
$("share-native").addEventListener("click", async () => {
  try {
    await navigator.share({ title: selectedSavedChat()?.title || "Sunoida chat", text: $("chat-share-text").value });
  } catch (error) {
    if (error.name !== "AbortError") $("chat-tools-status").textContent = "Device sharing is unavailable. You can copy the transcript instead.";
  }
});
$("download-saved-chat").addEventListener("click", () => {
  const chat = selectedSavedChat();
  if (chat) downloadTranscript(chat);
});
$("delete-chat").addEventListener("click", () => {
  showChatTool("chat-delete-panel");
  $("chat-delete-panel").querySelector(".chat-tool-back").focus();
});
$("confirm-delete-chat").addEventListener("click", deleteSavedChat);
$("close-preview").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  const box = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
});
$("previous-page").addEventListener("click", () => { if (state.viewer.page > 1) { state.viewer.page--; displayPage(); } });
$("next-page").addEventListener("click", () => { if (state.viewer.page < state.viewer.count) { state.viewer.page++; displayPage(); } });

window.addEventListener("resize", syncNavigation);
window.addEventListener("storage", (event) => {
  if (event.key === HISTORY_STORAGE_KEY || event.key === null) {
    state.history = loadHistory();
    if (state.history.deleted.includes(state.toolChatId) && chatTools.open) chatTools.close();
    if (state.history.deleted.includes(state.chatId)) activateChat(blankConversation(), false);
    else showHistory();
  }
});
syncNavigation();
renderConversation();
saveConversation();
requestJson("/api/guides").then((data) => {
  loadGuidePicker(data.guides || []);
}).catch((error) => {
  status.textContent = error.message;
});
