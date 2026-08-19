const allowedStatuses = new Set(["", "eligible", "needs_review", "below_threshold"]);
const allowedSorts = new Set(["recent", "oldest", "most_images", "review_priority"]);
const initialParams = new URLSearchParams(window.location.search);
const state = {
  q: initialParams.get("q") || "",
  tag: initialParams.get("tag") || "",
  status: allowedStatuses.has(initialParams.get("status") || "") ? initialParams.get("status") || "" : "",
  onlyNew: initialParams.get("new") === "1",
  sort: allowedSorts.has(initialParams.get("sort") || "") ? initialParams.get("sort") || "recent" : "recent",
  offset: 0,
  total: 0,
  loading: false,
  notes: [],
  tags: [],
  tagQuery: "",
  tagsExpanded: false,
  currentNoteKey: initialParams.get("note") || "",
  currentNote: null,
  viewerIndex: 0,
};

const limit = 24;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const masonry = $("#masonry");
const dialog = $("#note-dialog");
let notesController;
let notesRequestId = 0;
let searchTimer;
let toastTimer;
let toastCallback;

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

function syncUrl(noteKey = state.currentNoteKey) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.tag) params.set("tag", state.tag);
  if (state.status) params.set("status", state.status);
  if (state.onlyNew) params.set("new", "1");
  if (state.sort !== "recent") params.set("sort", state.sort);
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

function activeFilterCount() {
  return [state.q, state.tag, state.status, state.onlyNew].filter(Boolean).length;
}

function renderFilterState() {
  $("#search-input").value = state.q;
  $("#only-new").checked = state.onlyNew;
  $("#sort-select").value = state.sort;
  $$(".filter-button").forEach((button) => button.classList.toggle("active", button.dataset.status === state.status));
  const chips = [];
  if (state.q) chips.push(["q", `搜索：${state.q}`]);
  if (state.tag) chips.push(["tag", `标签：${state.tag}`]);
  if (state.status) chips.push(["status", labels[state.status]]);
  if (state.onlyNew) chips.push(["onlyNew", "仅看未推送"]);
  $("#active-filters").innerHTML = chips.map(([key, label]) =>
    `<button type="button" class="filter-chip" data-clear-filter="${key}">${escapeHtml(label)} <span aria-hidden="true">×</span></button>`
  ).join("");
  const count = activeFilterCount();
  const badge = $("#mobile-filter-count");
  badge.textContent = String(count);
  badge.hidden = count === 0;
}

function setFilter(key, value) {
  state[key] = value;
  renderFilterState();
  renderTags();
  syncUrl();
  loadNotes();
}

function renderCard(note) {
  const tags = note.tags.slice(0, 3).map((tag) => `<span class="card-tag">${escapeHtml(tag)}</span>`).join("");
  const image = note.preview_url
    ? `<img src="${escapeHtml(note.preview_url)}" loading="lazy" decoding="async" alt="${escapeHtml(note.search_keyword || "小红书素材")}" />`
    : `<div class="missing-cover" aria-hidden="true">XVI</div>`;
  const title = note.title || note.search_keyword || "未提取标题的笔记";
  const reviewed = note.accepted_count + note.rejected_count;
  const reviewedPercent = note.asset_count ? Math.round((reviewed / note.asset_count) * 100) : 0;
  const acceptedPercent = note.asset_count ? Math.round((note.accepted_count / note.asset_count) * 100) : 0;
  const delivery = note.delivery_status === "delivered" ? `<span class="delivery-marker">已推送</span>` : "";
  const metadata = [
    `${note.asset_count} 张图片`,
    note.author_name,
    note.last_captured_at ? `采集 ${formatDate(note.last_captured_at)}` : "",
  ].filter(Boolean).map((item) => `<span>${escapeHtml(item)}</span>`).join("<i>·</i>");
  return `<button class="note-card" type="button" data-note-key="${escapeHtml(note.note_key)}" aria-label="查看笔记：${escapeHtml(title)}">
    <div class="cover-wrap">${image}<span class="status-badge ${note.eligibility}">${labels[note.eligibility] || "待复核"}</span>${delivery}</div>
    <div class="card-body">
      <p class="card-title">${escapeHtml(title)}</p>
      <div class="card-meta">${metadata}</div>
      <div class="review-progress" title="已复核 ${reviewed}/${note.asset_count} 张"><span style="width:${reviewedPercent}%"><i style="width:${reviewedPercent ? Math.min(100, Math.round((acceptedPercent / reviewedPercent) * 100)) : 0}%"></i></span></div>
      <div class="card-review-summary"><span>${note.accepted_count} 符合</span><span>${note.rejected_count} 不符合</span><span>${note.needs_review_count} 待定</span></div>
      <div class="card-tags">${tags}</div>
    </div>
  </button>`;
}

function skeletonCards() {
  return Array.from({ length: 8 }, (_, index) => `<article class="note-card card-skeleton" aria-hidden="true"><div class="skeleton-cover" style="height:${220 + (index % 3) * 45}px"></div><div class="skeleton-lines"><i></i><i></i><i></i></div></article>`).join("");
}

function renderSummary(summary) {
  const items = [
    [summary.note_count, "已入库笔记", "", ""],
    [summary.asset_count, "可浏览图片", "", ""],
    [summary.eligible_count, "满足推送阈值", "accent", "eligible"],
    [summary.needs_review_count, "待复核笔记", "", "needs_review"],
    [summary.new_count, "尚未推送", "", "new"],
  ];
  $("#summary").innerHTML = items.map(([number, label, css, filter]) => {
    const tag = filter ? "button" : "article";
    const attributes = filter ? `type="button" data-summary-filter="${filter}"` : "";
    return `<${tag} ${attributes} class="summary-card ${css}"><span class="number">${number}</span><span class="label">${label}</span>${filter ? '<span class="summary-arrow">查看 →</span>' : ""}</${tag}>`;
  }).join("");
}

async function loadSummary() {
  renderSummary(await api("/api/v1/library/summary"));
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
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(state.offset),
    sort: state.sort,
  });
  if (state.q) params.set("q", state.q);
  if (state.tag) params.set("tag", state.tag);
  if (state.status) params.set("status", state.status);
  if (state.onlyNew) params.set("only_new", "true");
  return params;
}

async function loadNotes({ append = false } = {}) {
  if (append && state.loading) return;
  if (!append) {
    notesController?.abort();
    notesController = new AbortController();
    state.offset = 0;
  }
  const requestId = ++notesRequestId;
  state.loading = true;
  masonry.setAttribute("aria-busy", "true");
  if (!append) {
    if (!state.notes.length) masonry.innerHTML = skeletonCards();
    else masonry.classList.add("is-refreshing");
  }
  $("#load-more").disabled = true;
  try {
    const payload = await api(`/api/v1/library/notes?${notesParams()}`, { signal: notesController?.signal });
    if (requestId !== notesRequestId) return;
    state.total = payload.total;
    state.notes = append ? [...state.notes, ...payload.items] : payload.items;
    const markup = payload.items.map(renderCard).join("");
    if (append) masonry.insertAdjacentHTML("beforeend", markup);
    else masonry.innerHTML = markup;
    state.offset += payload.items.length;
    $("#result-count").textContent = payload.total
      ? `共 ${payload.total} 篇笔记 · 已展示 ${state.offset} 篇`
      : "没有找到匹配笔记";
    $("#empty-state").hidden = payload.total !== 0;
    $("#load-more").hidden = state.offset >= payload.total;
  } catch (error) {
    if (error.name !== "AbortError") {
      showToast(error.message);
      if (!append) masonry.innerHTML = `<div class="load-error"><strong>素材加载失败</strong><span>${escapeHtml(error.message)}</span><button type="button" data-retry>重新加载</button></div>`;
    }
  } finally {
    if (requestId === notesRequestId) {
      state.loading = false;
      masonry.classList.remove("is-refreshing");
      masonry.setAttribute("aria-busy", "false");
      $("#load-more").disabled = false;
    }
  }
}

async function refreshLibrary() {
  renderFilterState();
  const results = await Promise.allSettled([loadSummary(), loadTags(), loadNotes()]);
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
  return { index, loaded, total: state.total || loaded };
}

function renderNoteDetail(note, scrollTop = 0) {
  const source = note.source_url
    ? `<a class="external-link" href="${escapeHtml(note.source_url)}" target="_blank" rel="noreferrer">查看小红书原笔记 ↗</a><button type="button" class="copy-link-button" data-copy-link>复制链接</button>`
    : `<span class="detail-status">历史产物暂未恢复原链接</span>`;
  const images = note.assets.map((asset, index) => {
    const reasonId = `review-reason-${asset.asset_id}`;
    const humanReason = asset.human_review_reason || "";
    return `<article class="image-review-card ${asset.effective_review_status}">
      <button type="button" class="image-open-button" data-image-index="${index}" aria-label="放大查看第 ${asset.source_index + 1} 张图片">
        <img src="${escapeHtml(asset.media_url)}" loading="lazy" decoding="async" alt="笔记图片 ${asset.source_index + 1}" />
        <span class="zoom-hint">放大查看</span>
      </button>
      <footer class="image-review-footer">
        <span class="image-number">#${asset.source_index + 1}</span>
        ${reviewEvidence(asset)}
        <div class="review-choices" role="group" aria-label="图片 ${asset.source_index + 1} 复核结果">${reviewButtons(asset)}</div>
        <div class="review-note"><label for="${escapeHtml(reasonId)}">人工备注</label><div><input id="${escapeHtml(reasonId)}" data-review-reason data-asset-id="${escapeHtml(asset.asset_id)}" value="${escapeHtml(humanReason)}" maxlength="500" placeholder="补充符合或不符合的原因" /><button type="button" data-save-reason data-asset-id="${escapeHtml(asset.asset_id)}">保存</button></div></div>
      </footer>
    </article>`;
  }).join("");
  const { index, loaded, total } = currentNotePosition();
  const canPrevious = index > 0;
  const canNext = index >= 0 && (index < loaded - 1 || loaded < total);
  const deliveryLabel = note.delivery_status === "delivered" ? "撤销已推送" : "标记为已推送";
  const reviewed = note.accepted_count + note.rejected_count;
  const ratio = note.qualifying_ratio == null ? "—" : `${Math.round(note.qualifying_ratio * 100)}%`;
  $("#dialog-content").innerHTML = `<div class="detail-head">
    <div class="note-navigation"><button type="button" data-note-nav="previous" ${canPrevious ? "" : "disabled"}>← 上一篇</button><span>${index >= 0 ? `${index + 1} / ${total}` : "当前笔记"}</span><button type="button" data-note-nav="next" ${canNext ? "" : "disabled"}>下一篇 →</button></div>
    <p class="detail-kicker">${escapeHtml(note.search_keyword || "已入库素材")}</p>
    <h2 class="detail-title">${escapeHtml(note.title || "未提取标题的笔记")}</h2>
    <p class="detail-meta">${escapeHtml(note.author_name || "作者待补充")} · ${escapeHtml(note.published_at || "发布时间待补充")} · ${note.asset_count} 张图片</p>
  </div>
  <div class="detail-summary"><div><strong>${reviewed}/${note.asset_count}</strong><span>已复核</span></div><div><strong>${note.accepted_count}</strong><span>符合</span></div><div><strong>${note.rejected_count}</strong><span>不符合</span></div><div><strong>${ratio}</strong><span>符合率</span></div></div>
  <div class="detail-toolbar">
    <div class="detail-links">${source}<span class="detail-status ${note.eligibility}">${labels[note.eligibility]}</span></div>
    <div class="detail-actions"><button type="button" class="batch-button accepted" data-batch-review="accepted">全部标为符合</button><button type="button" class="batch-button rejected" data-batch-review="rejected">全部标为不符合</button><button type="button" id="delivery-button" class="primary-button ${note.delivery_status === "delivered" ? "secondary" : ""}" data-delivery-status="${note.delivery_status}">${deliveryLabel}</button></div>
  </div>
  <p class="review-hint">点击图片可放大；每张图片可直接选择“符合 / 不符合 / 待定”。批量操作会要求确认并可撤销。</p>
  <section class="image-review-grid">${images}</section>`;
  $("#dialog-content").scrollTop = scrollTop;
}

async function openNote(noteKey, { preserveScroll = false } = {}) {
  const scrollTop = preserveScroll ? $("#dialog-content").scrollTop : 0;
  try {
    const note = await api(`/api/v1/library/notes/${noteKey}`);
    state.currentNoteKey = noteKey;
    state.currentNote = note;
    renderNoteDetail(note, scrollTop);
    syncUrl(noteKey);
    if (!dialog.open) dialog.showModal();
  } catch (error) {
    showToast(error.message);
  }
}

function closeNote() {
  if (dialog.open) dialog.close();
}

async function refreshAfterReview() {
  await Promise.all([loadSummary(), loadNotes()]);
  if (state.currentNoteKey) await openNote(state.currentNoteKey, { preserveScroll: true });
}

async function saveReview(assetId, status, reason = null) {
  return api(`/api/v1/library/assets/${assetId}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, reviewer: "网页复核", reason }),
  });
}

async function updateAssetReview(button) {
  const assetId = button.dataset.assetId;
  const asset = state.currentNote?.assets.find((item) => item.asset_id === assetId);
  if (!asset || asset.effective_review_status === button.dataset.reviewStatus) return;
  const previousStatus = asset.effective_review_status;
  const previousReason = asset.human_review_reason || null;
  const card = button.closest(".image-review-card");
  card?.classList.add("is-saving");
  try {
    await saveReview(assetId, button.dataset.reviewStatus, previousReason);
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

async function saveReviewReason(button) {
  const assetId = button.dataset.assetId;
  const asset = state.currentNote?.assets.find((item) => item.asset_id === assetId);
  const input = button.closest(".review-note")?.querySelector("[data-review-reason]");
  if (!asset || !input) return;
  const previousReason = asset.human_review_reason || null;
  const reason = input.value.trim() || null;
  if (reason === previousReason) {
    showToast("备注没有变化");
    return;
  }
  const card = button.closest(".image-review-card");
  card?.classList.add("is-saving");
  try {
    await saveReview(assetId, asset.effective_review_status, reason);
    await refreshAfterReview();
    showToast("人工备注已保存", {
      label: "撤销",
      callback: async () => {
        await saveReview(assetId, asset.effective_review_status, previousReason);
        await refreshAfterReview();
        showToast("已撤销备注修改");
      },
    });
  } catch (error) {
    card?.classList.remove("is-saving");
    showToast(error.message);
  }
}

async function batchReview(status) {
  const note = state.currentNote;
  if (!note) return;
  const changed = note.assets.filter((asset) => asset.effective_review_status !== status);
  if (!changed.length) {
    showToast("当前图片已经全部是该状态");
    return;
  }
  if (!window.confirm(`确认将本篇 ${changed.length} 张图片全部标记为“${labels[status]}”吗？`)) return;
  const previous = changed.map((asset) => ({
    assetId: asset.asset_id,
    status: asset.effective_review_status,
    reason: asset.human_review_reason || null,
  }));
  try {
    await Promise.all(changed.map((asset) => saveReview(asset.asset_id, status, asset.human_review_reason || null)));
    await refreshAfterReview();
    showToast(`已批量更新 ${changed.length} 张图片`, {
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
  let target = state.notes[index + direction];
  if (direction > 0 && !target && index >= 0 && state.notes.length < state.total) {
    await loadNotes({ append: true });
    const refreshedIndex = state.notes.findIndex((note) => note.note_key === state.currentNoteKey);
    target = state.notes[refreshedIndex + direction];
  }
  if (target) await openNote(target.note_key);
}

function openFilters() {
  $("#filter-sidebar").classList.add("is-open");
  $("#filter-backdrop").hidden = false;
  $("#mobile-filter-button").setAttribute("aria-expanded", "true");
  document.body.classList.add("filters-open");
}

function closeFilters() {
  $("#filter-sidebar").classList.remove("is-open");
  $("#filter-backdrop").hidden = true;
  $("#mobile-filter-button").setAttribute("aria-expanded", "false");
  document.body.classList.remove("filters-open");
}

function resetFilters() {
  Object.assign(state, { q: "", tag: "", status: "", onlyNew: false, sort: "recent" });
  state.tagQuery = "";
  state.tagsExpanded = false;
  $("#tag-search-input").value = "";
  renderFilterState();
  renderTags();
  syncUrl();
  loadNotes();
}

$("#search-input").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => setFilter("q", event.target.value.trim()), 260);
});
$("#only-new").addEventListener("change", (event) => setFilter("onlyNew", event.target.checked));
$("#sort-select").addEventListener("change", (event) => setFilter("sort", event.target.value));
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
  setFilter(key, key === "onlyNew" ? false : "");
});
$("#summary").addEventListener("click", (event) => {
  const card = event.target.closest("[data-summary-filter]");
  if (!card?.dataset.summaryFilter) return;
  if (card.dataset.summaryFilter === "new") setFilter("onlyNew", true);
  else setFilter("status", card.dataset.summaryFilter);
  window.scrollTo({ top: $("#active-filters").offsetTop - 96, behavior: "smooth" });
});
$("#load-more").addEventListener("click", () => loadNotes({ append: true }));
masonry.addEventListener("click", (event) => {
  const retry = event.target.closest("[data-retry]");
  if (retry) loadNotes();
  const card = event.target.closest("[data-note-key]");
  if (card) openNote(card.dataset.noteKey);
});
$("#close-dialog").addEventListener("click", closeNote);
dialog.addEventListener("click", (event) => { if (event.target === dialog) closeNote(); });
dialog.addEventListener("cancel", (event) => {
  if (!$("#image-viewer").hidden) {
    event.preventDefault();
    closeViewer();
  }
});
dialog.addEventListener("close", () => {
  state.currentNoteKey = "";
  state.currentNote = null;
  syncUrl("");
});
$("#dialog-content").addEventListener("click", (event) => {
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
$("#mobile-filter-button").addEventListener("click", openFilters);
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
    if (event.key === "ArrowLeft") navigateNote(-1);
    if (event.key === "ArrowRight") navigateNote(1);
  }
});
$("#reindex-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "正在同步…";
  try {
    const result = await api("/api/v1/library/reindex", { method: "POST" });
    showToast(`同步完成：${result.asset_count} 张本地图片`);
    await refreshLibrary();
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
});

new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && !state.loading && state.offset < state.total) loadNotes({ append: true });
}, { rootMargin: "500px" }).observe($("#load-sentinel"));

refreshLibrary().then(() => {
  if (state.currentNoteKey) openNote(state.currentNoteKey);
});
