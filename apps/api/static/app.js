const state = { q: "", tag: "", status: "", onlyNew: false, offset: 0, total: 0, loading: false };
const limit = 24;
const $ = (selector) => document.querySelector(selector);
const masonry = $("#masonry");
const dialog = $("#note-dialog");
let toastTimer;

const labels = {
  eligible: "满足推送阈值",
  needs_review: "待复核",
  below_threshold: "未达阈值",
  accepted: "符合",
  rejected: "不符合",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#039;", '"': "&quot;",
  })[character]);
}

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "请求失败");
  return response.json();
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2500);
}

function statusClass(status) { return status || "needs_review"; }

function renderCard(note) {
  const tags = note.tags.slice(0, 3).map((tag) => `<span class="card-tag">${escapeHtml(tag)}</span>`).join("");
  const image = note.preview_url
    ? `<img src="${note.preview_url}" loading="lazy" alt="${escapeHtml(note.search_keyword || "小红书素材")}" />`
    : "";
  const title = note.title || note.search_keyword || "未提取标题的笔记";
  const progress = `${note.accepted_count} 符合 · ${note.rejected_count} 不符合 · ${note.needs_review_count} 待定`;
  return `<button class="note-card" data-note-key="${note.note_key}">
    <div class="cover-wrap">${image}<span class="status-badge ${statusClass(note.eligibility)}">${labels[note.eligibility]}</span></div>
    <div class="card-body"><p class="card-title">${escapeHtml(title)}</p>
      <div class="card-meta"><span>${note.asset_count} 张图片</span><span>·</span><span>${escapeHtml(note.author_name || "作者待补充")}</span></div>
      <div class="card-meta"><span>${progress}</span></div><div class="card-tags">${tags}</div>
    </div></button>`;
}

function renderSummary(summary) {
  const items = [
    [summary.note_count, "已入库笔记"], [summary.asset_count, "可浏览图片"],
    [summary.eligible_count, "满足推送阈值", "accent"], [summary.needs_review_count, "待复核笔记"],
  ];
  $("#summary").innerHTML = items.map(([number, label, css]) =>
    `<article class="summary-card ${css || ""}"><div class="number">${number}</div><div class="label">${label}</div></article>`).join("");
}

async function loadTags() {
  const { items } = await api("/api/v1/library/tags");
  const max = 24;
  $("#tag-filters").innerHTML = items.slice(0, max).map(({ tag, note_count }) =>
    `<button class="tag ${state.tag === tag ? "active" : ""}" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)} <small>${note_count}</small></button>`).join("");
}

async function loadSummary() { renderSummary(await api("/api/v1/library/summary")); }

async function loadNotes({ append = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  if (!append) { state.offset = 0; masonry.innerHTML = ""; }
  const params = new URLSearchParams({ limit: String(limit), offset: String(state.offset) });
  if (state.q) params.set("q", state.q);
  if (state.tag) params.set("tag", state.tag);
  if (state.status) params.set("status", state.status);
  if (state.onlyNew) params.set("only_new", "true");
  try {
    const payload = await api(`/api/v1/library/notes?${params}`);
    state.total = payload.total;
    masonry.insertAdjacentHTML("beforeend", payload.items.map(renderCard).join(""));
    state.offset += payload.items.length;
    $("#result-count").textContent = `找到 ${payload.total} 篇笔记 · 当前展示 ${state.offset} 篇`;
    $("#empty-state").hidden = payload.total !== 0;
    $("#load-more").hidden = state.offset >= payload.total;
  } catch (error) {
    showToast(error.message);
  } finally { state.loading = false; }
}

async function refreshLibrary() {
  await Promise.all([loadSummary(), loadTags(), loadNotes()]);
}

function reviewOptions(selected) {
  return [
    ["needs_review", "待复核"], ["accepted", "符合"], ["rejected", "不符合"],
  ].map(([value, label]) => `<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`).join("");
}

async function openNote(noteKey) {
  try {
    const note = await api(`/api/v1/library/notes/${noteKey}`);
    const source = note.source_url
      ? `<a class="external-link" href="${escapeHtml(note.source_url)}" target="_blank" rel="noreferrer">前往小红书原笔记 ↗</a>`
      : `<span class="detail-status">历史产物暂未恢复原链接</span>`;
    const deliveryLabel = note.delivery_status === "delivered" ? "标记为未推送" : "标记为已推送";
    const images = note.assets.map((asset) => `<article class="image-review-card">
      <img src="${asset.media_url}" loading="lazy" alt="笔记图片 ${asset.source_index + 1}" />
      <footer class="image-review-footer"><span>#${asset.source_index + 1}</span>
      <select class="review-select" data-asset-id="${asset.asset_id}" aria-label="图片 ${asset.source_index + 1} 复核结果">${reviewOptions(asset.effective_review_status)}</select></footer>
    </article>`).join("");
    $("#dialog-content").innerHTML = `<div class="detail-head"><p class="detail-kicker">${escapeHtml(note.search_keyword || "已入库素材")}</p>
      <h2 class="detail-title">${escapeHtml(note.title || "未提取标题的笔记")}</h2>
      <p class="detail-meta">${escapeHtml(note.author_name || "作者待补充")} · ${escapeHtml(note.published_at || "发布时间待补充")} · ${note.asset_count} 张图片</p></div>
      <div class="detail-actions">${source}<span class="detail-status">${labels[note.eligibility]} · ${note.accepted_count}/${note.asset_count} 符合</span>
      <button id="delivery-button" class="primary-button" data-note-key="${note.note_key}" data-delivery-status="${note.delivery_status}">${deliveryLabel}</button></div>
      <section class="image-review-grid">${images}</section>`;
    dialog.showModal();
  } catch (error) { showToast(error.message); }
}

async function updateAssetReview(select) {
  const assetId = select.dataset.assetId;
  try {
    await api(`/api/v1/library/assets/${assetId}/review`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: select.value, reviewer: "网页复核" }),
    });
    showToast("复核结果已保存");
    await Promise.all([loadSummary(), loadNotes()]);
  } catch (error) { showToast(error.message); }
}

async function toggleDelivery(button) {
  const current = button.dataset.deliveryStatus;
  try {
    await api(`/api/v1/library/notes/${button.dataset.noteKey}/delivery`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: current === "delivered" ? "new" : "delivered" }),
    });
    showToast("推送状态已更新");
    dialog.close();
    await Promise.all([loadSummary(), loadNotes()]);
  } catch (error) { showToast(error.message); }
}

let searchTimer;
$("#search-input").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = event.target.value.trim(); loadNotes(); }, 260);
});
$("#only-new").addEventListener("change", (event) => { state.onlyNew = event.target.checked; loadNotes(); });
$("#status-filters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-status]"); if (!button) return;
  state.status = button.dataset.status;
  document.querySelectorAll(".filter-button").forEach((node) => node.classList.toggle("active", node === button));
  loadNotes();
});
$("#tag-filters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tag]"); if (!button) return;
  state.tag = state.tag === button.dataset.tag ? "" : button.dataset.tag;
  loadTags(); loadNotes();
});
$("#reset-filters").addEventListener("click", () => {
  state.q = state.tag = state.status = ""; state.onlyNew = false;
  $("#search-input").value = ""; $("#only-new").checked = false;
  document.querySelectorAll(".filter-button").forEach((node, index) => node.classList.toggle("active", index === 0));
  loadTags(); loadNotes();
});
$("#load-more").addEventListener("click", () => loadNotes({ append: true }));
masonry.addEventListener("click", (event) => { const card = event.target.closest("[data-note-key]"); if (card) openNote(card.dataset.noteKey); });
$("#close-dialog").addEventListener("click", () => dialog.close());
$("#dialog-content").addEventListener("change", (event) => { if (event.target.matches(".review-select")) updateAssetReview(event.target); });
$("#dialog-content").addEventListener("click", (event) => { const button = event.target.closest("#delivery-button"); if (button) toggleDelivery(button); });
$("#reindex-button").addEventListener("click", async () => {
  try { const result = await api("/api/v1/library/reindex", { method: "POST" }); showToast(`已读取 ${result.asset_count} 张本地图片`); await refreshLibrary(); }
  catch (error) { showToast(error.message); }
});
document.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#search-input").focus(); } });

refreshLibrary();
