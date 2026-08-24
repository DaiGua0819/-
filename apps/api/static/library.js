const allowedStatuses = new Set(["", "eligible", "needs_review", "below_threshold"]);
const allowedSorts = new Set(["recent", "oldest", "most_images", "review_priority"]);
const FAVORITES_STORAGE_KEY = "xhs-material-favorites";

function loadFavoriteKeys() {
  try {
    const value = JSON.parse(window.localStorage.getItem(FAVORITES_STORAGE_KEY) || "[]");
    return new Set(Array.isArray(value) ? value.filter(Boolean) : []);
  } catch {
    return new Set();
  }
}

function persistFavoriteKeys() {
  try {
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify([...state.favoriteKeys]));
  } catch {
    // 收藏功能在禁用 localStorage 的浏览器中仍可临时使用。
  }
}

const initialParams = new URLSearchParams(window.location.search);
const initialPage = Math.max(1, Number.parseInt(initialParams.get("page") || "1", 10) || 1);
const state = {
  q: initialParams.get("q") || "",
  tag: initialParams.get("tag") || "",
  status: allowedStatuses.has(initialParams.get("status") || "") ? initialParams.get("status") || "" : "",
  onlyNew: initialParams.get("new") === "1",
  sort: allowedSorts.has(initialParams.get("sort") || "") ? initialParams.get("sort") || "recent" : "recent",
  page: initialPage,
  totalPages: 0,
  offset: 0,
  total: 0,
  loading: false,
  notes: [],
  tags: [],
  tagQuery: "",
  tagsExpanded: false,
  favoritesOnly: initialParams.get("view") === "favorites",
  favoriteKeys: loadFavoriteKeys(),
  currentNoteKey: initialParams.get("note") || "",
  currentNote: null,
  detailImageIndex: 0,
  viewerIndex: 0,
};

const pageSize = 25;
const $ = (selector) => document.querySelector(selector);
const NOTE_LIST_CACHE_LIMIT = 12;
const NOTE_DETAIL_CACHE_LIMIT = 36;
const DETAIL_IMAGE_TRANSITION_MS = 200;
const $$ = (selector) => [...document.querySelectorAll(selector)];
const masonry = $("#masonry");
const dialog = $("#note-dialog");
let notesController;
let notesRequestId = 0;
let searchTimer;
let toastTimer;
let toastCallback;
let dialogAnimationTimer;
let activeNoteOrigin = null;
let noteCloseInProgress = false;
const reasonSaveTimers = new Map();
const reasonSaveOperations = new Set();
const savedReasonSelector = "[data-saved-reason]";

const noteListCache = new Map();
const noteDetailCache = new Map();
const preloadedAssetUrls = new Set();
let detailRequestId = 0;
let detailImageTransitionId = 0;
let lastNoteTrigger = null;
const reducedMotionQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");

function prefersLightweightEffects() {
  return Boolean(reducedMotionQuery?.matches || navigator.connection?.saveData || (navigator.deviceMemory && navigator.deviceMemory <= 4));
}
const labels = {
  eligible: "满足推送阈值",
  needs_review: "待复核",
  below_threshold: "未达阈值",
  accepted: "符合",
  rejected: "不符合",
};


function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#039;",
    '"': "&quot;",
  })[character]);
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "请求失败，请稍后重试");
  }
  return response.json();
}

function updateEffectMode() {
  document.documentElement.classList.toggle("performance-lite", prefersLightweightEffects());
}

function rememberCacheEntry(cache, key, value, limit) {
  cache.delete(key);
  cache.set(key, { value, cachedAt: Date.now() });
  while (cache.size > limit) cache.delete(cache.keys().next().value);
}

function readCacheEntry(cache, key) {
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.cachedAt > 60_000) {
    cache.delete(key);
    return null;
  }
  cache.delete(key);
  cache.set(key, entry);
  return entry.value;
}

function clearLibraryCaches() {
  noteListCache.clear();
  noteDetailCache.clear();
}

function preloadAssetUrl(url) {
  if (!url || preloadedAssetUrls.has(url)) return;
  preloadedAssetUrls.add(url);
  const image = new Image();
  image.decoding = "async";
  image.src = url;
}

function preloadAdjacentAssets(note, index) {
  const assets = note?.assets || [];
  [index - 1, index + 1]
    .filter((candidate) => candidate >= 0 && candidate < assets.length)
    .forEach((candidate) => preloadAssetUrl(assets[candidate]?.media_url));
}

async function getNoteDetail(noteKey, { force = false } = {}) {
  if (!force) {
    const cached = readCacheEntry(noteDetailCache, noteKey);
    if (cached) return cached;
  }
  const note = await api(`/api/v1/library/notes/${noteKey}`);
  rememberCacheEntry(noteDetailCache, noteKey, note, NOTE_DETAIL_CACHE_LIMIT);
  return note;
}

updateEffectMode();
reducedMotionQuery?.addEventListener?.("change", updateEffectMode);
function syncUrl(noteKey = state.currentNoteKey) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.tag) params.set("tag", state.tag);
  if (state.status) params.set("status", state.status);
  if (state.onlyNew) params.set("new", "1");
  if (state.sort !== "recent") params.set("sort", state.sort);
  if (state.favoritesOnly) params.set("view", "favorites");
  if (state.page > 1) params.set("page", String(state.page));
  if (noteKey) params.set("note", noteKey);
  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

function showToast(message, action = null) {
  $("#toast-message").textContent = message;
  const actionButton = $("#toast-action");
  toastCallback = action?.callback || null;
  actionButton.textContent = action?.label || "";
  actionButton.hidden = !toastCallback;
  $("#toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.remove("show"), action ? 6000 : 2800);
}

function renderFilterState() {
  $("#search-input").value = state.q;
  $("#only-new").checked = state.onlyNew;
  $$(".filter-button").forEach((button) => button.classList.toggle("active", button.dataset.status === state.status));
  const homeNav = $("#home-nav");
  const favoritesNav = $("#favorites-nav");
  homeNav?.classList.toggle("active", !state.favoritesOnly);
  favoritesNav?.classList.toggle("active", state.favoritesOnly);
  if (homeNav) {
    if (state.favoritesOnly) homeNav.removeAttribute("aria-current");
    else homeNav.setAttribute("aria-current", "page");
  }
  if (favoritesNav) favoritesNav.setAttribute("aria-pressed", String(state.favoritesOnly));
  const chips = [];
  if (state.q) chips.push(["q", `搜索：${state.q}`]);
  if (state.tag) chips.push(["tag", `标签：${state.tag}`]);
  if (state.status) chips.push(["status", labels[state.status]]);
  if (state.onlyNew) chips.push(["onlyNew", "仅看未推送"]);
  if (state.favoritesOnly) chips.push(["favoritesOnly", "我的喜欢"]);
  $("#active-filters").innerHTML = chips.map(([key, label]) =>
    `<button type="button" class="filter-chip" data-clear-filter="${key}">${escapeHtml(label)} <span aria-hidden="true">×</span></button>`
  ).join("");
}

function setFilter(key, value) {
  state[key] = value;
  state.page = 1;
  renderFilterState();
  renderTags();
  syncUrl();
  loadNotes({ page: 1 });
}

function isFavorite(noteKey) {
  return Boolean(noteKey) && state.favoriteKeys.has(noteKey);
}

function setFavoritesView(enabled) {
  state.favoritesOnly = enabled;
  state.page = 1;
  if (enabled) {
    state.q = "";
    state.tag = "";
    state.status = "";
    state.onlyNew = false;
    state.tagQuery = "";
    state.tagsExpanded = false;
    $("#tag-search-input").value = "";
    if (dialog.open) closeNote();
  }
  renderFilterState();
  renderTags();
  syncUrl("");
  loadNotes({ page: 1 });
}

function toggleFavorite(noteKey) {
  if (!noteKey) return;
  const added = !state.favoriteKeys.has(noteKey);
  if (added) state.favoriteKeys.add(noteKey);
  else state.favoriteKeys.delete(noteKey);
  persistFavoriteKeys();
  renderFilterState();
  if (state.currentNoteKey === noteKey && state.currentNote) {
    renderNoteDetail(state.currentNote, $("#dialog-content").scrollTop);
  }
  if (state.favoritesOnly) loadNotes({ page: state.page });
  showToast(added ? "已加入我的喜欢" : "已移出我的喜欢");
}

function renderCard(note) {
  const tags = (note.tags || []).slice(0, 3).map((tag) => `<span class="card-tag">${escapeHtml(tag)}</span>`).join("");
  const image = note.preview_url
    ? `<img src="${escapeHtml(note.preview_url)}" loading="lazy" decoding="async" alt="${escapeHtml(note.search_keyword || "小红书素材")}" />`
    : `<div class="missing-cover" aria-hidden="true">XVI</div>`;
  const title = note.title || note.search_keyword || "未提取标题的笔记";
  const reviewed = note.accepted_count + note.rejected_count;
  const reviewedPercent = note.asset_count ? Math.round((reviewed / note.asset_count) * 100) : 0;
  const acceptedPercent = note.asset_count ? Math.round((note.accepted_count / note.asset_count) * 100) : 0;
  const delivery = note.delivery_status === "delivered" ? `<span class="delivery-marker">已推送</span>` : "";
  const metadata = [
    note.asset_count ? note.asset_count + " 张图片" : "",
    note.author_name || "",
  ].filter(Boolean).map((item) => "<span>" + escapeHtml(item) + "</span>").join("<i>·</i>");
  const dates = [
    note.published_at ? "发布 " + note.published_at : "",
    note.last_captured_at ? "采集 " + formatDate(note.last_captured_at) : "",
  ].filter(Boolean).map((item) => "<span>" + escapeHtml(item) + "</span>").join("<i>·</i>");
  return `<button class="note-card" type="button" data-note-key="${escapeHtml(note.note_key)}" aria-label="查看笔记：${escapeHtml(title)}">
    <div class="cover-wrap">${image}<span class="status-badge ${note.eligibility}">${labels[note.eligibility] || "待复核"}</span>${delivery}</div>
    <div class="card-body">
      <div class="card-meta">${metadata}</div>
      <div class="card-date">${dates}</div>
      <div class="review-progress" title="已复核 ${reviewed}/${note.asset_count} 张"><span style="width:${reviewedPercent}%"><i style="width:${reviewedPercent ? Math.min(100, Math.round((acceptedPercent / reviewedPercent) * 100)) : 0}%"></i></span></div>
      <div class="card-review-summary"><span>${note.accepted_count} 符合</span><span>${note.rejected_count} 不符合</span><span>${note.needs_review_count} 待定</span></div>
      <div class="card-tags">${tags}</div>
    </div>
  </button>`;
}

function skeletonCards() {
  return Array.from({ length: 8 }, (_, index) => `<article class="note-card card-skeleton" aria-hidden="true"><div class="skeleton-cover" style="height:${220 + (index % 3) * 45}px"></div><div class="skeleton-lines"><i></i><i></i><i></i></div></article>`).join("");
}

function renderTags() {
  const query = state.tagQuery.trim().toLocaleLowerCase("zh-CN");
  let items = state.tags.filter(({ tag }) => !query || tag.toLocaleLowerCase("zh-CN").includes(query));
  items = [...items].sort((left, right) => Number(right.tag === state.tag) - Number(left.tag === state.tag));
  const visible = state.tagsExpanded || query ? items : items.slice(0, 24);
  $("#tag-filters").innerHTML = visible.length
    ? visible.map(({ tag, note_count: noteCount }) => `<button type="button" class="tag ${state.tag === tag ? "active" : ""}" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)} <small>${noteCount}</small></button>`).join("")
    : `<p class="tag-empty">没有匹配标签</p>`;
  const toggle = $("#toggle-tags");
  toggle.hidden = Boolean(query) || items.length <= 24;
  toggle.textContent = state.tagsExpanded ? "收起标签" : `显示其余 ${Math.max(items.length - 24, 0)} 个标签`;
}

async function loadTags() {
  const { items } = await api("/api/v1/library/tags");
  state.tags = items;
  renderTags();
}

function notesParams() {
  const requestLimit = state.favoritesOnly ? 200 : pageSize;
  const requestOffset = state.favoritesOnly ? 0 : (state.page - 1) * pageSize;
  const params = new URLSearchParams({
    limit: String(requestLimit),
    offset: String(requestOffset),
    sort: state.sort,
  });
  if (state.q) params.set("q", state.q);
  if (state.tag) params.set("tag", state.tag);
  if (state.status) params.set("status", state.status);
  if (state.onlyNew) params.set("only_new", "true");
  return params;
}

function renderPagination() {
  const pagination = $("#pagination");
  const pageNumbers = $("#page-numbers");
  const previous = $("#page-previous");
  const next = $("#page-next");
  if (!pagination || !pageNumbers || !previous || !next) return;
  const totalPages = state.totalPages;
  if (totalPages <= 1) {
    pagination.hidden = true;
    pageNumbers.innerHTML = "";
    return;
  }
  pagination.hidden = false;
  previous.disabled = state.page <= 1;
  previous.dataset.page = String(Math.max(1, state.page - 1));
  next.disabled = state.page >= totalPages;
  next.dataset.page = String(Math.min(totalPages, state.page + 1));
  const maxButtons = 7;
  const endPage = Math.min(totalPages, Math.max(state.page + 3, maxButtons));
  const startPage = Math.max(1, Math.min(state.page - 3, endPage - maxButtons + 1));
  pageNumbers.innerHTML = Array.from({ length: endPage - startPage + 1 }, (_, index) => {
    const page = startPage + index;
    const active = page === state.page;
    return '<button type="button" class="pagination-number' + (active ? ' active' : '') + '" data-page="' + page + '" aria-label="第 ' + page + ' 页"' + (active ? ' aria-current="page"' : '') + '>' + page + '</button>';
  }).join("");
}

function revealMasonry() {
  if (prefersLightweightEffects()) return;
  masonry.classList.remove("is-revealing");
  void masonry.offsetWidth;
  masonry.classList.add("is-revealing");
  window.setTimeout(() => masonry.classList.remove("is-revealing"), 180);
}

async function loadNotes({ page = state.page, force = false } = {}) {
  notesController?.abort();
  notesController = new AbortController();
  state.page = Math.max(1, Number(page) || 1);
  const requestId = ++notesRequestId;
  const cacheKey = notesParams();
  state.loading = true;
  masonry.setAttribute("aria-busy", "true");
  masonry.dataset.loading = "true";
  if (!state.notes.length) masonry.innerHTML = skeletonCards();
  else masonry.classList.add("is-refreshing");
  try {
    const cachedPayload = force ? null : readCacheEntry(noteListCache, cacheKey);
    const payload = cachedPayload || await api("/api/v1/library/notes?" + cacheKey, { signal: notesController?.signal });
    if (!cachedPayload) rememberCacheEntry(noteListCache, cacheKey, payload, NOTE_LIST_CACHE_LIMIT);
    if (requestId !== notesRequestId) return;
    const fetchedItems = payload.items || [];
    const favoriteItems = state.favoritesOnly
      ? fetchedItems.filter((note) => isFavorite(note.note_key))
      : fetchedItems;
    state.total = state.favoritesOnly ? favoriteItems.length : Number(payload.total || fetchedItems.length);
    state.totalPages = state.total ? Math.ceil(state.total / pageSize) : 0;
    if (state.totalPages && state.page > state.totalPages) {
      state.page = state.totalPages;
      syncUrl();
      return loadNotes({ page: state.page, force });
    }
    const start = (state.page - 1) * pageSize;
    const visibleItems = state.favoritesOnly ? favoriteItems.slice(start, start + pageSize) : fetchedItems;
    state.notes = visibleItems;
    state.offset = start + visibleItems.length;
    masonry.innerHTML = visibleItems.map(renderCard).join("");
    revealMasonry();
    const emptyTitle = $("#empty-state h2");
    const emptyCopy = $("#empty-state p");
    if (state.favoritesOnly) {
      emptyTitle.textContent = "还没有喜欢的素材";
      emptyCopy.textContent = "在笔记详情中点击喜欢，素材会出现在这里。";
    } else {
      emptyTitle.textContent = "没有匹配的笔记";
      emptyCopy.textContent = "试试清除筛选或改用更短的关键词。";
    }
    $("#empty-state").hidden = state.total !== 0;
    renderPagination();
  } catch (error) {
    if (error.name !== "AbortError") {
      showToast(error.message);
      masonry.innerHTML = '<div class="load-error"><strong>素材加载失败</strong><span>' + escapeHtml(error.message) + '</span><button type="button" data-retry>重新加载</button></div>';
    }
  } finally {
    if (requestId === notesRequestId) {
      state.loading = false;
      masonry.classList.remove("is-refreshing");
      masonry.removeAttribute("data-loading");
      masonry.setAttribute("aria-busy", "false");
    }
  }
}
async function refreshLibrary() {
  renderFilterState();
  const results = await Promise.allSettled([loadTags(), loadNotes({ force: true })]);
  const failure = results.find((result) => result.status === "rejected");
  if (failure?.status === "rejected") {
    showToast(failure.reason?.message || "部分数据加载失败，请稍后重试");
  }
}

function reviewButtons(asset) {
  return [
    ["accepted", "符合"],
    ["rejected", "不符合"],
    ["needs_review", "待定"],
  ].map(([status, label]) => `<button type="button" class="review-choice ${asset.effective_review_status === status ? "active" : ""}" data-review-status="${status}" data-asset-id="${asset.asset_id}" aria-pressed="${asset.effective_review_status === status}">${label}</button>`).join("");
}

function reviewEvidence(asset) {
  const aiStatus = asset.ai_requirement_status ? labels[asset.ai_requirement_status] : "未判断";
  const aiReason = asset.ai_requirement_reason || "暂无 AI 判断说明";
  const humanSource = asset.review_source === "web_review" ? "人工复核" : "历史复核";
  const humanDecision = asset.human_review_status
    ? `<p class="human-evidence"><span>${humanSource}</span><strong class="${asset.human_review_status}">${labels[asset.human_review_status] || "待定"}</strong></p>`
    : "";
  return `<div class="review-evidence"><p class="ai-evidence"><span>AI 建议</span><strong class="${asset.ai_requirement_status || "unknown"}">${aiStatus}</strong></p><p class="evidence-reason">${escapeHtml(aiReason)}</p>${humanDecision}</div>`;
}

function currentNotePosition() {
  const index = state.notes.findIndex((note) => note.note_key === state.currentNoteKey);
  const loaded = state.notes.length;
  const globalIndex = index >= 0 ? (state.page - 1) * pageSize + index : -1;
  return { index, globalIndex, loaded, total: state.total || loaded };
}

function renderCarouselMedia(note) {
  const assets = note.assets || [];
  if (!assets.length) {
    return '<section id="detail-media" class="detail-media-column"><div class="detail-media-empty"><strong>暂无可展示图片</strong><span>这篇笔记没有成功恢复图片素材。</span></div></section>';
  }
  const currentIndex = Math.min(Math.max(Number(state.detailImageIndex) || 0, 0), assets.length - 1);
  state.detailImageIndex = currentIndex;
  const asset = assets[currentIndex];
  const dots = assets.map((item, index) => '<button type="button" class="detail-dot ' + (index === currentIndex ? "active" : "") + '" data-carousel-index="' + index + '" aria-label="切换到第 ' + (index + 1) + ' 张图片" aria-current="' + (index === currentIndex ? "true" : "false") + '"></button>').join("");
  return '<section id="detail-media" class="detail-media-column">' +
    '<div class="detail-media-stage">' +
      '<img class="detail-media-backdrop" src="' + escapeHtml(asset.media_url) + '" aria-hidden="true" alt="" decoding="async" />' +
      '<button type="button" class="detail-carousel-nav previous" data-carousel-nav="-1" aria-label="上一张图片" ' + (currentIndex === 0 ? "disabled" : "") + '>‹</button>' +
      '<button type="button" class="detail-hero-button" data-image-index="' + currentIndex + '" aria-label="查看第 ' + (currentIndex + 1) + ' 张图片大图"><img class="detail-hero-image is-current" src="' + escapeHtml(asset.media_url) + '" decoding="async" alt="笔记图片 ' + (asset.source_index || currentIndex + 1) + '" /><span class="detail-hero-count">' + (currentIndex + 1) + ' / ' + assets.length + '</span></button>' +
      '<button type="button" class="detail-carousel-nav next" data-carousel-nav="1" aria-label="下一张图片" ' + (currentIndex === assets.length - 1 ? "disabled" : "") + '>›</button>' +
    '</div>' +
    '<div class="detail-thumbs" aria-label="图片导航"><div class="detail-dot-row" aria-label="图片位置">' + dots + '</div></div>' +
  '</section>';
}

function clampDetailImageIndex(index, assets) {
  return Math.min(Math.max(Number(index) || 0, 0), Math.max(assets.length - 1, 0));
}

function updateDetailMediaControls(note, index) {
  const assets = note.assets || [];
  const media = $("#detail-media");
  if (!media || !assets.length) return;
  const hero = media.querySelector(".detail-hero-button");
  const previous = media.querySelector('[data-carousel-nav="-1"]');
  const next = media.querySelector('[data-carousel-nav="1"]');
  if (hero) {
    hero.dataset.imageIndex = String(index);
    hero.setAttribute("aria-label", "查看第 " + (index + 1) + " 张图片大图");
  }
  if (previous) previous.disabled = index === 0;
  if (next) next.disabled = index === assets.length - 1;
  media.querySelectorAll("[data-carousel-index]").forEach((dot) => {
    const isActive = Number(dot.dataset.carouselIndex) === index;
    dot.classList.toggle("active", isActive);
    dot.setAttribute("aria-current", String(isActive));
  });
}

function setDetailImage(index) {
  const note = state.currentNote;
  const assets = note?.assets || [];
  if (!assets.length) return;
  const previousIndex = state.detailImageIndex;
  const nextIndex = clampDetailImageIndex(index, assets);
  if (nextIndex === previousIndex) return;

  const media = $("#detail-media");
  const hero = media?.querySelector(".detail-hero-button");
  if (!media || !hero) {
    state.detailImageIndex = nextIndex;
    renderNoteDetail(note, $("#dialog-content").scrollTop);
    preloadAdjacentAssets(note, nextIndex);
    return;
  }

  const transitionId = ++detailImageTransitionId;
  const nextAsset = assets[nextIndex];
  state.detailImageIndex = nextIndex;
  updateDetailMediaControls(note, nextIndex);
  const incoming = new Image();
  incoming.className = "detail-hero-image is-entering " + (nextIndex > previousIndex ? "from-next" : "from-previous");
  incoming.decoding = "async";
  incoming.alt = "笔记图片 " + (nextAsset.source_index || nextIndex + 1);

  const showNextImage = () => {
    if (transitionId !== detailImageTransitionId || !hero.isConnected) return;
    const outgoingImages = [...hero.querySelectorAll(".detail-hero-image")];
    const outgoingDirection = nextIndex > previousIndex ? "to-previous" : "to-next";
    outgoingImages.forEach((image) => {
      image.classList.remove("is-current", "is-entering", "is-visible", "from-next", "from-previous", "to-next", "to-previous");
      image.classList.add("is-leaving", outgoingDirection);
    });
    hero.append(incoming);
    requestAnimationFrame(() => incoming.classList.add("is-visible"));
    const backdrop = media.querySelector(".detail-media-backdrop");
    if (backdrop) backdrop.src = nextAsset.media_url;
    window.setTimeout(() => {
      if (transitionId !== detailImageTransitionId) return;
      outgoingImages.forEach((image) => image.remove());
      incoming.classList.remove("is-entering", "is-visible", "from-next", "from-previous");
      incoming.classList.add("is-current");
    }, DETAIL_IMAGE_TRANSITION_MS);
    preloadAdjacentAssets(note, nextIndex);
  };

  incoming.addEventListener("load", showNextImage, { once: true });
  incoming.addEventListener("error", () => {
    if (transitionId !== detailImageTransitionId) return;
    state.detailImageIndex = previousIndex;
    updateDetailMediaControls(note, previousIndex);
    showToast("图片加载失败，请重试");
  }, { once: true });
  incoming.src = nextAsset.media_url;
  if (incoming.complete && incoming.naturalWidth) showNextImage();
}
function renderNoteDetail(note, scrollTop = 0) {
  const assets = note.assets || [];
  const source = note.source_url
    ? '<a class="external-link" href="' + escapeHtml(note.source_url) + '" target="_blank" rel="noreferrer">查看小红书原笔记 ↗</a><button type="button" class="copy-link-button" data-copy-link>复制链接</button>'
    : '<span class="detail-status">历史产物暂未恢复原链接</span>';
  const { index, globalIndex, total } = currentNotePosition();
  const canPrevious = index > 0 || globalIndex > 0;
  const canNext = globalIndex >= 0 && globalIndex < total - 1;
  const ratio = note.qualifying_ratio == null ? "—" : Math.round(note.qualifying_ratio * 100) + "%";
  const authorName = note.author_name || "作者待补充";
  const favorite = isFavorite(note.note_key);
  const detailQueryTags = String(note.search_keyword || "已入库素材")
    .split(/[\s,，|\/]+/)
    .filter(Boolean)
    .map((tag) => '<span class="detail-query-pill">' + escapeHtml(tag) + '</span>')
    .join("");
  const detailFacts = [
    note.published_at_raw || note.published_at ? '<span class="detail-published-date">发布 ' + escapeHtml(note.published_at_raw || note.published_at) + '</span>' : "",
    note.edited_at_raw ? '<span>编辑 ' + escapeHtml(note.edited_at_raw) + '</span>' : "",
    note.platform_note_id ? '<span>笔记ID ' + escapeHtml(note.platform_note_id) + '</span>' : "",
  ].filter(Boolean).join("");
  const detailBody = note.body_text
    ? '<div class="detail-body">' + escapeHtml(note.body_text) + '</div>'
    : '<p class="detail-empty-copy">暂无正文内容。</p>';
  const detailTags = (note.tags || []).length
    ? '<div class="detail-tags">' + note.tags.map((tag) => '<span class="card-tag">' + escapeHtml(tag) + '</span>').join("") + '</div>'
    : '<p class="detail-empty-copy">暂无标签。</p>';
  const detailCaptureError = note.capture_error_reason
    ? '<p class="detail-error">采集记录：' + escapeHtml(note.capture_error_code || "capture_incomplete") + " · " + escapeHtml(note.capture_error_reason) + '</p>'
    : "";
  const detailLinks = '<div class="detail-links">' + source + '</div>';
  const favoriteButton = '<button type="button" class="favorite-button ' + (favorite ? "active" : "") + '" data-favorite-note="' + escapeHtml(note.note_key) + '" aria-pressed="' + String(favorite) + '"><span aria-hidden="true">' + (favorite ? "♥" : "♡") + '</span><span>' + (favorite ? "已喜欢" : "喜欢") + '</span></button>';
  const media = renderCarouselMedia(note);
  $("#dialog-content").innerHTML =
    '<div class="detail-head">' +
      '<div class="note-navigation"><button type="button" data-note-nav="previous" ' + (canPrevious ? "" : "disabled") + '>← 上一篇</button><span>' + (globalIndex >= 0 ? (globalIndex + 1) + " / " + total : "当前笔记") + '</span><button type="button" data-note-nav="next" ' + (canNext ? "" : "disabled") + '>下一篇 →</button></div>' +
    '</div>' +
    '<section class="detail-layout">' +
      media +
      '<section class="detail-info">' +
        '<div class="detail-author-row"><div class="detail-author"><strong>' + escapeHtml(authorName) + '</strong></div><div class="detail-top-actions">' + favoriteButton + detailLinks + '</div></div>' +
        '<div class="detail-query-tags">' + detailQueryTags + '</div>' +
        '<h2 class="detail-title">' + escapeHtml(note.title || "未提取标题的笔记") + '</h2>' +
        '<div class="detail-facts">' + detailFacts + '</div>' +
        '<div class="detail-copy">' + detailBody + '</div>' +
        '<div class="detail-tag-block"><span class="detail-section-label">标签</span>' + detailTags + '</div>' +
        '<div class="detail-summary"><div><strong>' + note.accepted_count + '</strong><span>符合</span></div><div><strong>' + note.rejected_count + '</strong><span>不符合</span></div><div><strong>' + ratio + '</strong><span>符合率</span></div></div>' +
        detailCaptureError +
      '</section>' +
    '</section>';
  $("#dialog-content").scrollTop = scrollTop;
}

function captureNoteOrigin(card) {
  if (!card) return null;
  const source = card.querySelector(".cover-wrap img") || card.querySelector(".cover-wrap");
  if (!source) return null;
  const rect = source.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
}

function clearNoteOriginStyles() {
  dialog.style.removeProperty("--note-origin-dx");
  dialog.style.removeProperty("--note-origin-dy");
  dialog.style.removeProperty("--note-origin-sx");
  dialog.style.removeProperty("--note-origin-sy");
}

function applyNoteOrigin(origin) {
  clearNoteOriginStyles();
  if (!origin) return;
  const target = dialog.getBoundingClientRect();
  if (!target.width || !target.height) return;
  const sourceCenterX = origin.left + origin.width / 2;
  const sourceCenterY = origin.top + origin.height / 2;
  const targetCenterX = target.left + target.width / 2;
  const targetCenterY = target.top + target.height / 2;
  const scaleX = Math.max(0.08, Math.min(1, origin.width / target.width));
  const scaleY = Math.max(0.08, Math.min(1, origin.height / target.height));
  dialog.style.setProperty("--note-origin-dx", `${sourceCenterX - targetCenterX}px`);
  dialog.style.setProperty("--note-origin-dy", `${sourceCenterY - targetCenterY}px`);
  dialog.style.setProperty("--note-origin-sx", String(scaleX));
  dialog.style.setProperty("--note-origin-sy", String(scaleY));
}

function originIsVisible(origin) {
  if (!origin) return false;
  return origin.width > 0
    && origin.height > 0
    && origin.left < window.innerWidth
    && origin.top < window.innerHeight
    && origin.left + origin.width > 0
    && origin.top + origin.height > 0;
}

function resolveActiveNoteOrigin() {
  if (!activeNoteOrigin) return null;
  const card = $$("[data-note-key]").find((candidate) => candidate.dataset.noteKey === activeNoteOrigin.noteKey);
  const origin = captureNoteOrigin(card);
  return originIsVisible(origin) ? origin : null;
}

async function openNote(noteKey, { preserveScroll = false, origin = null, force = false } = {}) {
  if (dialog.open && state.currentNoteKey && state.currentNoteKey !== noteKey) {
    await flushPendingReasonSaves();
  }
  const requestId = ++detailRequestId;
  const scrollTop = preserveScroll ? $("#dialog-content").scrollTop : 0;
  const shouldResetDetailImage = !state.currentNote || state.currentNoteKey !== noteKey;
  try {
    const note = await getNoteDetail(noteKey, { force });
    if (requestId !== detailRequestId) return;
    if (shouldResetDetailImage) state.detailImageIndex = 0;
    state.currentNoteKey = noteKey;
    state.currentNote = note;
    renderNoteDetail(note, scrollTop);
    preloadAdjacentAssets(note, state.detailImageIndex);
    syncUrl(noteKey);
    if (!dialog.open) {
      activeNoteOrigin = origin ? { ...origin, noteKey } : null;
      clearTimeout(dialogAnimationTimer);
      dialog.classList.remove("is-opening", "is-closing", "has-note-origin");
      clearNoteOriginStyles();
      dialog.showModal();
      requestAnimationFrame(() => {
        if (!dialog.open || requestId !== detailRequestId) return;
        applyNoteOrigin(origin);
        dialog.classList.add("is-opening");
        dialogAnimationTimer = window.setTimeout(() => {
          dialog.classList.remove("is-opening");
          clearNoteOriginStyles();
        }, 600);
      });
    }
  } catch (error) {
    if (requestId === detailRequestId) showToast(error.message);
  }
}

async function closeNote() {
  if (!dialog.open || noteCloseInProgress) return;
  noteCloseInProgress = true;
  await flushPendingReasonSaves();
  if (!dialog.open) {
    noteCloseInProgress = false;
    return;
  }
  clearTimeout(dialogAnimationTimer);
  dialog.classList.remove("is-opening", "is-closing", "has-note-origin");
  clearNoteOriginStyles();
  const origin = resolveActiveNoteOrigin();
  if (origin) {
    applyNoteOrigin(origin);
    dialog.classList.add("has-note-origin");
  }
  dialog.classList.add("is-closing");
  dialogAnimationTimer = window.setTimeout(() => {
    if (dialog.open) dialog.close();
  }, 600);
}

async function refreshAfterReview() {
  clearLibraryCaches();
  await loadNotes({ force: true });
  if (state.currentNoteKey) await openNote(state.currentNoteKey, { preserveScroll: true, force: true });
}

async function saveReview(assetId, status, reason = null) {
  return api(`/api/v1/library/assets/${assetId}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, reviewer: "网页复核", reason }),
  });
}

function normalizeReason(value) {
  return value.trim() || null;
}

function reviewReasonInput(assetId) {
  return $$("[data-review-reason]").find((input) => input.dataset.assetId === assetId);
}

function draftReason(asset) {
  const input = reviewReasonInput(asset.asset_id);
  return input ? normalizeReason(input.value) : asset.human_review_reason || null;
}

function clearReasonTimer(assetId) {
  clearTimeout(reasonSaveTimers.get(assetId));
  reasonSaveTimers.delete(assetId);
}

function setReasonStatus(input, status, message) {
  const container = input.closest(".review-note");
  container?.classList.remove("dirty", "saving", "saved", "error");
  if (status) container?.classList.add(status);
  const label = container?.querySelector("[data-reason-status]");
  if (label) label.textContent = message;
}
async function flushPendingReasonSaves() {
  const buttons = [...reasonSaveTimers.keys()].map((assetId) => {
    const input = reviewReasonInput(assetId);
    return input?.closest(".review-note")?.querySelector("[data-save-reason]");
  }).filter(Boolean);
  if (buttons.length) {
    await Promise.all(buttons.map((button) => saveReviewReason(button, { silent: true })));
  }
  if (reasonSaveOperations.size) await Promise.allSettled([...reasonSaveOperations]);
}


async function updateAssetReview(button) {
  const assetId = button.dataset.assetId;
  const asset = state.currentNote?.assets.find((item) => item.asset_id === assetId);
  if (!asset) return;
  const previousStatus = asset.effective_review_status;
  const previousReason = asset.human_review_reason || null;
  const reason = draftReason(asset);
  if (previousStatus === button.dataset.reviewStatus && reason === previousReason) {
    showToast("状态和备注没有变化");
    return;
  }
  clearReasonTimer(assetId);
  const card = button.closest(".image-review-card");
  card?.classList.add("is-saving");
  try {
    await saveReview(assetId, button.dataset.reviewStatus, reason);
    await refreshAfterReview();
    showToast("复核结果已保存", {
      label: "撤销",
      callback: async () => {
        await saveReview(assetId, previousStatus, previousReason);
        await refreshAfterReview();
        showToast("已撤销上次复核");
      },
    });
  } catch (error) {
    card?.classList.remove("is-saving");
    showToast(error.message);
  }
}

async function saveReviewReason(button, { silent = false } = {}) {
  const assetId = button.dataset.assetId;
  const asset = state.currentNote?.assets.find((item) => item.asset_id === assetId);
  const input = button.closest(".review-note")?.querySelector("[data-review-reason]");
  if (!asset || !input) return;
  clearReasonTimer(assetId);
  const previousReason = asset.human_review_reason || null;
  const reason = normalizeReason(input.value);
  if (reason === previousReason) {
    setReasonStatus(input, previousReason ? "saved" : "", previousReason ? "已保存" : "");
    if (!silent) showToast("备注没有变化");
    return;
  }
  button.disabled = true;
  setReasonStatus(input, "saving", "保存中…");
  const operation = saveReview(assetId, asset.effective_review_status, reason);
  reasonSaveOperations.add(operation);
  try {
    await operation;
    asset.human_review_reason = reason;
    asset.human_review_status = asset.effective_review_status;
    asset.review_source = "web_review";
    input.dataset.savedReason = reason || "";
    setReasonStatus(input, "saved", reason ? "已保存" : "已清空");
    if (!silent) {
      showToast("人工备注已保存", {
        label: "撤销",
        callback: async () => {
          await saveReview(assetId, asset.effective_review_status, previousReason);
          asset.human_review_reason = previousReason;
          input.value = previousReason || "";
          input.dataset.savedReason = previousReason || "";
          setReasonStatus(input, previousReason ? "saved" : "", previousReason ? "已保存" : "");
          showToast("已撤销备注修改");
        },
      });
    }
  } catch (error) {
    setReasonStatus(input, "error", "保存失败");
    showToast(silent ? `备注自动保存失败：${error.message}` : error.message);
  } finally {
    reasonSaveOperations.delete(operation);
    button.disabled = false;
  }
}

async function batchReview(status) {
  const note = state.currentNote;
  if (!note) return;
  const changes = note.assets.map((asset) => ({ asset, reason: draftReason(asset) })).filter(
    ({ asset, reason }) => asset.effective_review_status !== status || reason !== (asset.human_review_reason || null),
  );
  if (!changes.length) {
    showToast("当前图片状态和备注都没有变化");
    return;
  }
  if (!window.confirm(`确认更新本篇 ${changes.length} 张图片并保存当前备注吗？`)) return;
  const previous = changes.map(({ asset }) => ({
    assetId: asset.asset_id,
    status: asset.effective_review_status,
    reason: asset.human_review_reason || null,
  }));
  changes.forEach(({ asset }) => clearReasonTimer(asset.asset_id));
  try {
    await Promise.all(changes.map(({ asset, reason }) => saveReview(asset.asset_id, status, reason)));
    await refreshAfterReview();
    showToast(`已批量更新 ${changes.length} 张图片`, {
      label: "撤销",
      callback: async () => {
        await Promise.all(previous.map((item) => saveReview(item.assetId, item.status, item.reason)));
        await refreshAfterReview();
        showToast("已撤销批量复核");
      },
    });
  } catch (error) {
    showToast(`${error.message}，请刷新确认结果`);
  }
}

async function toggleDelivery(button) {
  const previousStatus = button.dataset.deliveryStatus;
  const nextStatus = previousStatus === "delivered" ? "new" : "delivered";
  const noteKey = state.currentNoteKey;
  try {
    await api(`/api/v1/library/notes/${noteKey}/delivery`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: nextStatus }),
    });
    await refreshAfterReview();
    showToast(nextStatus === "delivered" ? "已标记为已推送" : "已恢复为未推送", {
      label: "撤销",
      callback: async () => {
        await api(`/api/v1/library/notes/${noteKey}/delivery`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: previousStatus }),
        });
        await refreshAfterReview();
        showToast("已撤销推送状态修改");
      },
    });
  } catch (error) {
    showToast(error.message);
  }
}

async function copySourceLink() {
  if (!state.currentNote?.source_url) return;
  try {
    await navigator.clipboard.writeText(state.currentNote.source_url);
    showToast("原笔记链接已复制");
  } catch {
    showToast("浏览器未允许复制，请打开原笔记后复制地址");
  }
}

function showViewer(index) {
  if (!state.currentNote?.assets[index]) return;
  state.viewerIndex = index;
  const asset = state.currentNote.assets[index];
  $("#viewer-image").src = asset.media_url;
  $("#viewer-caption").textContent = `${state.viewerIndex + 1} / ${state.currentNote.assets.length}`;
  $("#previous-image").disabled = index === 0;
  $("#next-image").disabled = index === state.currentNote.assets.length - 1;
  $("#image-viewer").hidden = false;
  document.body.classList.add("no-scroll");
  $("#close-image-viewer").focus();
}

function closeViewer() {
  $("#image-viewer").hidden = true;
  $("#viewer-image").removeAttribute("src");
  document.body.classList.remove("no-scroll");
}

function navigateViewer(direction) {
  const next = state.viewerIndex + direction;
  if (next >= 0 && next < (state.currentNote?.assets.length || 0)) showViewer(next);
}

async function navigateNote(direction) {
  const { index } = currentNotePosition();
  let target = index >= 0 ? state.notes[index + direction] : null;
  if (!target) {
    const targetPage = state.page + (direction > 0 ? 1 : -1);
    if (targetPage >= 1 && targetPage <= state.totalPages) {
      await loadNotes({ page: targetPage });
      target = direction > 0 ? state.notes[0] : state.notes[state.notes.length - 1];
    }
  }
  if (target) await openNote(target.note_key);
}

function closeFilters() {
  $("#filter-sidebar").classList.remove("is-open");
  $("#filter-backdrop").hidden = true;
  document.body.classList.remove("filters-open");
}

function resetFilters() {
  Object.assign(state, { q: "", tag: "", status: "", onlyNew: false, sort: "recent", page: 1 });
  state.tagQuery = "";
  state.tagsExpanded = false;
  $("#tag-search-input").value = "";
  renderFilterState();
  renderTags();
  syncUrl();
  loadNotes({ page: 1 });
}

$("#search-input").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => setFilter("q", event.target.value.trim()), 260);
});
$("#only-new").addEventListener("change", (event) => setFilter("onlyNew", event.target.checked));
$("#status-filters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-status]");
  if (button) setFilter("status", button.dataset.status);
});
$("#tag-filters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tag]");
  if (button) setFilter("tag", state.tag === button.dataset.tag ? "" : button.dataset.tag);
});
$("#tag-search-input").addEventListener("input", (event) => {
  state.tagQuery = event.target.value;
  renderTags();
});
$("#toggle-tags").addEventListener("click", () => {
  state.tagsExpanded = !state.tagsExpanded;
  renderTags();
});
$("#reset-filters").addEventListener("click", resetFilters);
$("#active-filters").addEventListener("click", (event) => {
  const chip = event.target.closest("[data-clear-filter]");
  if (!chip) return;
  const key = chip.dataset.clearFilter;
  if (key === "favoritesOnly") {
    setFavoritesView(false);
    return;
  }
  setFilter(key, key === "onlyNew" ? false : "");
});
$("#pagination").addEventListener("click", (event) => {
  const button = event.target.closest("[data-page]");
  if (!button || button.disabled) return;
  const page = Number(button.dataset.page);
  if (!Number.isInteger(page) || page < 1 || page === state.page) return;
  state.page = page;
  syncUrl();
  loadNotes({ page });
});
masonry.addEventListener("click", (event) => {
  const retry = event.target.closest("[data-retry]");
  if (retry) loadNotes();
  const card = event.target.closest("[data-note-key]");
  if (card) {
    lastNoteTrigger = card;
    openNote(card.dataset.noteKey, { origin: captureNoteOrigin(card) });
  }
});
$("#favorites-nav").addEventListener("click", () => setFavoritesView(true));
$("#home-nav").addEventListener("click", (event) => {
  if (!state.favoritesOnly) return;
  event.preventDefault();
  setFavoritesView(false);
});
$("#close-dialog").addEventListener("click", closeNote);
dialog.addEventListener("click", (event) => { if (event.target === dialog) closeNote(); });
dialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  if (noteCloseInProgress) return;
  if (!$("#image-viewer").hidden) {
    closeViewer();
    return;
  }
  closeNote();
});
dialog.addEventListener("close", () => {
  clearTimeout(dialogAnimationTimer);
  const focusKey = activeNoteOrigin?.noteKey || state.currentNoteKey;
  const fallbackTarget = focusKey ? $$("[data-note-key]").find((candidate) => candidate.dataset.noteKey === focusKey) : null;
  const focusTarget = lastNoteTrigger?.isConnected ? lastNoteTrigger : fallbackTarget;
  dialog.classList.remove("is-opening", "is-closing", "has-note-origin");
  clearNoteOriginStyles();
  activeNoteOrigin = null;
  noteCloseInProgress = false;
  state.currentNoteKey = "";
  state.currentNote = null;
  syncUrl("");
  requestAnimationFrame(() => {
    if (focusTarget?.isConnected) focusTarget.focus({ preventScroll: true });
  });
  lastNoteTrigger = null;
});
$("#dialog-content").addEventListener("click", (event) => {
  const favorite = event.target.closest("[data-favorite-note]");
  if (favorite) {
    toggleFavorite(favorite.dataset.favoriteNote);
    return;
  }
  const carousel = event.target.closest("[data-carousel-index]");
  if (carousel) {
    setDetailImage(Number(carousel.dataset.carouselIndex));
    return;
  }
  const carouselNavigation = event.target.closest("[data-carousel-nav]");
  if (carouselNavigation) {
    setDetailImage(state.detailImageIndex + Number(carouselNavigation.dataset.carouselNav));
    return;
  }
  const review = event.target.closest("[data-review-status]");
  if (review) updateAssetReview(review);
  const reasonButton = event.target.closest("[data-save-reason]");
  if (reasonButton) saveReviewReason(reasonButton);
  const batch = event.target.closest("[data-batch-review]");
  if (batch) batchReview(batch.dataset.batchReview);
  const delivery = event.target.closest("#delivery-button");
  if (delivery) toggleDelivery(delivery);
  if (event.target.closest("[data-copy-link]")) copySourceLink();
  const image = event.target.closest("[data-image-index]");
  if (image) showViewer(Number(image.dataset.imageIndex));
  const navigation = event.target.closest("[data-note-nav]");
  if (navigation) navigateNote(navigation.dataset.noteNav === "next" ? 1 : -1);
});
$("#dialog-content").addEventListener("input", (event) => {
  if (!event.target.matches("[data-review-reason]")) return;
  const input = event.target;
  const assetId = input.dataset.assetId;
  const button = input.closest(".review-note")?.querySelector("[data-save-reason]");
  if (!assetId || !button) return;
  clearReasonTimer(assetId);
  const savedReason = normalizeReason(input.dataset.savedReason || "");
  if (normalizeReason(input.value) === savedReason) {
    setReasonStatus(input, savedReason ? "saved" : "", savedReason ? "已保存" : "");
    return;
  }
  setReasonStatus(input, "dirty", "等待自动保存");
  const timer = setTimeout(() => saveReviewReason(button, { silent: true }), 700);
  reasonSaveTimers.set(assetId, timer);
});

$("#dialog-content").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || !event.target.matches("[data-review-reason]")) return;
  event.preventDefault();
  const button = event.target.closest(".review-note")?.querySelector("[data-save-reason]");
  if (button) saveReviewReason(button);
});

$("#toast-action").addEventListener("click", async () => {
  const callback = toastCallback;
  toastCallback = null;
  $("#toast-action").hidden = true;
  if (callback) await callback();
});
$("#close-image-viewer").addEventListener("click", closeViewer);
$("#previous-image").addEventListener("click", () => navigateViewer(-1));
$("#next-image").addEventListener("click", () => navigateViewer(1));
$("#image-viewer").addEventListener("click", (event) => { if (event.target === $("#image-viewer")) closeViewer(); });
$("#close-filters").addEventListener("click", closeFilters);
$("#filter-backdrop").addEventListener("click", closeFilters);
$("#apply-mobile-filters").addEventListener("click", closeFilters);
$("#back-to-top").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
window.addEventListener("scroll", () => { $("#back-to-top").hidden = window.scrollY < 700; }, { passive: true });
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    $("#search-input").focus();
    return;
  }
  if (!$("#image-viewer").hidden) {
    event.preventDefault();
    if (event.key === "Escape") closeViewer();
    if (event.key === "ArrowLeft") navigateViewer(-1);
    if (event.key === "ArrowRight") navigateViewer(1);
    return;
  }
  if (dialog.open && !event.target.matches("input, select, textarea, button")) {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setDetailImage(state.detailImageIndex - 1);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      setDetailImage(state.detailImageIndex + 1);
    }
  }
});
window.addEventListener("beforeunload", (event) => {
  if (!reasonSaveTimers.size && !reasonSaveOperations.size) return;
  event.preventDefault();
  event.returnValue = "";
});

// 分页网格不再使用无限滚动；IntersectionObserver 与 state.notes.length < state.total
// 仅保留为兼容旧页面集成的语义，不会触发额外请求。

refreshLibrary().then(() => {
  if (state.currentNoteKey) openNote(state.currentNoteKey);
});
