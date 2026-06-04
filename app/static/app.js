const $ = (selector) => document.querySelector(selector);

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText);
  return data;
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

const STATUS_LABELS = {
  queued: "排队中",
  running: "运行中",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
  cancelling: "取消中",
};

const TABS = {
  running: { label: "运行中", statuses: ["running"] },
  queued: { label: "排队中", statuses: ["queued"] },
  failed: { label: "失败任务", statuses: ["failed"] },
  completed: { label: "已完成", statuses: ["done"] },
  cancelled: { label: "已取消", statuses: ["cancelled", "cancelling"] },
};

const PAGE_SIZE = 5;
let currentTab = "running";
let pageByTab = { running: 1, queued: 1, failed: 1, completed: 1, cancelled: 1 };
let allJobs = [];

function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return "";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}m${r}s`;
}

function elapsedSeconds(startedAt) {
  if (!startedAt || startedAt === 0) return 0;
  return Math.floor(Date.now() / 1000 - startedAt);
}

function fmtClock(ts) {
  if (!ts || ts === 0) return "";
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour12: false });
}

function fmtDate(ts) {
  if (!ts || ts === 0) return "";
  const d = new Date(ts * 1000);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}


async function loadConfig() {
  const config = await api("/api/config");
  for (const [key, value] of Object.entries(config)) {
    const input = document.querySelector(`[name="${key}"]`);
    if (!input) continue;
    if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else if (value != null && !String(value).includes("***")) {
      input.value = value;
    }
  }
  if (config.dbo_api_url) DBO_BASE = config.dbo_api_url;
  if (config.dbo_api_key) DBO_KEY = config.dbo_api_key;
  $("#config-status").textContent = JSON.stringify(config, null, 2);
}

async function cancelJob(jobId) {
  try {
    await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
  } catch (error) {
    alert(error.message);
  }
  await loadJobs();
}

async function retryJob(jobId) {
  try {
    await api(`/api/jobs/${jobId}/retry`, { method: "POST" });
  } catch (error) {
    alert(error.message);
  }
  currentTab = "queued";
  await loadJobs();
}

async function deleteJob(jobId) {
  if (!confirm("确定删除此任务？")) return;
  try {
    await api(`/api/jobs/${jobId}`, { method: "DELETE" });
  } catch (e) {
    alert("删除失败: " + e.message);
  }
  await loadJobs();
}

async function retryAllFailedJobs() {
  try {
    const result = await api("/api/jobs/retry-failed", { method: "POST" });
    if (result.retried > 0) {
      $("#job-status").textContent = `已批量重试 ${result.retried} 个失败任务`;
    } else {
      $("#job-status").textContent = "当前没有可重试的失败任务";
    }
  } catch (error) {
    alert(error.message);
  }
  currentTab = "queued";
  await loadJobs();
}

function renderJobCard(job) {
  const cancellable = job.status === "queued" || job.status === "running";
  const retryable = job.status === "failed" || job.status === "cancelled" || job.status === "cancelling";
  const statusLabel = STATUS_LABELS[job.status] || job.status;

  let timingHtml = "";
  if (job.status === "running" && job.started_at) {
    const el = elapsedSeconds(job.started_at);
    timingHtml = `<span class="timing">已运行 ${fmtDuration(el)}</span>`;
  }

  let completedHtml = "";
  if ((job.status === "done" || job.status === "failed" || job.status === "cancelled") && job.completed_at) {
    const label = job.status === "cancelled" ? "取消时间" : "完成时间";
    completedHtml = `<span class="completed-time">${label} ${fmtDate(job.completed_at)} ${fmtClock(job.completed_at)}</span>`;
  }

  let progressHtml = "";
  if (job.progress > 0 && (job.status === "running" || job.status === "cancelling")) {
    let phaseClass = "progress-local";
    if (job.progress >= 90) phaseClass = "progress-final";
    else if (job.progress >= 40) phaseClass = "progress-cloud";
    progressHtml = `<div class="progress-bar"><div class="progress-fill ${phaseClass}" style="width:${Math.min(job.progress, 100)}%"></div></div>`;
  }

  const actions = [];
  if (retryable) {
    const retryLabel = job.status === "cancelled" ? "重新加入任务队列" : "重试";
    actions.push(`<button class="retry-btn" data-id="${job.id}">${retryLabel}</button>`);
  }
  if (cancellable) actions.push(`<button class="cancel-btn" data-id="${job.id}">取消</button>`);
  actions.push(`<button class="delete-btn" data-id="${job.id}">删除</button>`);

  return `
    <article class="job ${escapeHtml(job.status)}">
      <div class="job-head">
        <strong>${escapeHtml(statusLabel)}</strong>
        <span>${escapeHtml(job.id.slice(0, 8))}</span>
        ${timingHtml}
        <span class="head-spacer"></span>
        <div class="job-actions">${actions.join("")}</div>
      </div>
      ${progressHtml}
      <p class="job-path">${escapeHtml(job.input_path)}</p>
      <p class="job-msg">${escapeHtml(job.message || "")}</p>
      ${completedHtml}
      <small>${escapeHtml((job.output_files || []).join("\n"))}</small>
    </article>
  `;
}

async function loadJobs() {
  allJobs = await api("/api/jobs");
  renderTab(currentTab);
}

function getJobsForTab(tab) {
  const filtered = allJobs.filter((j) => TABS[tab].statuses.includes(j.status));
  // 排队中的按创建时间升序（最早的在前，FIFO）
  if (tab === "queued") {
    return filtered.sort((a, b) => a.created_at - b.created_at);
  }
  // 运行中的按开始时间升序（先开始的在上）
  if (tab === "running") {
    return filtered.sort((a, b) => a.started_at - b.started_at);
  }
  return filtered;
}

function renderTab(tab) {
  const tabJobs = getJobsForTab(tab);
  const totalPages = Math.ceil(tabJobs.length / PAGE_SIZE) || 1;
  let page = pageByTab[tab];
  if (page > totalPages) page = totalPages;
  pageByTab[tab] = page;
  const start = (page - 1) * PAGE_SIZE;
  const pageJobs = tabJobs.slice(start, start + PAGE_SIZE);

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const t = btn.dataset.tab;
    const count = getJobsForTab(t).length;
    btn.textContent = `${TABS[t].label} (${count})`;
    btn.classList.toggle("active", t === currentTab);
  });

  const failedTools = $("#failed-tools");
  const failedToolsText = $("#failed-tools-text");
  if (failedTools && failedToolsText) {
    const failedCount = getJobsForTab("failed").length;
    failedToolsText.textContent = `当前有 ${failedCount} 个失败任务`;
    failedTools.classList.toggle("hidden", tab !== "failed");
  }

  document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
  const pane = document.getElementById("tab-" + tab);
  if (pane) pane.classList.add("active");

  const jobsEl = pane ? pane.querySelector(".jobs") : null;
  if (jobsEl) {
    jobsEl.innerHTML = pageJobs.map(renderJobCard).join("") || "<p class='empty'>暂无任务</p>";
  }

  document.querySelectorAll(".cancel-btn").forEach((btn) => {
    btn.addEventListener("click", () => cancelJob(btn.dataset.id));
  });

  document.querySelectorAll(".retry-btn").forEach((btn) => {
    btn.addEventListener("click", () => retryJob(btn.dataset.id));
  });

  document.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", () => deleteJob(btn.dataset.id));
  });

  const pagerEl = pane ? pane.querySelector(".pager") : null;
  if (pagerEl) {
    pagerEl.innerHTML = totalPages <= 1 ? "" : `
      <button ${page <= 1 ? "disabled" : ""} data-action="prev">上一页</button>
      <span>${page} / ${totalPages}</span>
      <button ${page >= totalPages ? "disabled" : ""} data-action="next">下一页</button>
    `;
    pagerEl.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.action === "prev" && page > 1) pageByTab[currentTab] = page - 1;
        if (btn.dataset.action === "next" && page < totalPages) pageByTab[currentTab] = page + 1;
        renderTab(currentTab);
      });
    });
  }
}

function switchTab(tab) {
  currentTab = tab;
  renderTab(tab);
}

$("#config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.target);
  data.default_timeout_seconds = Number(data.default_timeout_seconds || 7200);
  data.watchdog_interval_seconds = Number(data.watchdog_interval_seconds || 60);
  data.max_workers = Number(data.max_workers || 1);
  data.enable_watchdog = Boolean(event.target.enable_watchdog.checked);
  try {
    const saved = await api("/api/config", { method: "POST", body: JSON.stringify(data) });
    showToast("✅ 配置已保存");
  } catch (error) {
    showToast("保存失败: " + error.message, false);
  }
});

$("#job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.target);
  data.formats = String(data.formats || "srt").split(",").map((x) => x.trim()).filter(Boolean);
  data.overwrite = Boolean(event.target.overwrite.checked);
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(data) });
    $("#job-status").textContent = "✅ 加入队列成功！";
    await loadJobs();
  } catch (error) {
    $("#job-status").textContent = error.message;
  }
});

function showToast(msg, ok = true) {
  const t = document.createElement("div");
  t.className = "toast " + (ok ? "toast-ok" : "toast-err");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

$("#test-dbo-btn")?.addEventListener("click", async () => {
  const btn = $("#test-dbo-btn");
  btn.disabled = true; btn.textContent = "检测中...";
  try {
    const r = await api("/api/test-dbo", { method: "POST" });
    if (r.ok) btn.textContent = `✅ DBO 连通 ${r.latency_ms}ms`;
    else btn.textContent = `❌ ${r.error || "失败"}`;
  } catch (e) {
    btn.textContent = "❌ " + e.message.slice(0,30);
  }
  btn.disabled = false;
  setTimeout(() => { btn.textContent = "测试 DBO 连通性"; }, 5000);
});

$("#refresh").addEventListener("click", loadJobs);
api("/api/version").then(r => { const v = $("#version"); if (v) v.textContent = r.version; });

$("#clear-audio")?.addEventListener("click", async () => {
  if (!confirm("确定清空音频缓存？已缓存的文件下次需要重新提取。")) return;
  try {
    const r = await api("/api/clear-audio-cache", { method: "POST" });
    alert("已清除 " + r.removed + " 个音频缓存文件");
  } catch (e) {
    alert("清除失败: " + e.message);
  }
});
$("#retry-all-failed")?.addEventListener("click", retryAllFailedJobs);
loadConfig().catch((error) => $("#config-status").textContent = error.message);

// Combined override: gallery refresh + splash hide


/* ═══ POSTER CACHE ═══ */
const posterCache = new Map();
const pendingFetches = new Map();
const posterQueue = [];

let DBO_BASE = "";
let DBO_KEY = "";
const LS_PREFIX = "poster_";

// 从 localStorage 恢复缓存（自动清理旧格式 dbo 直连 URL 和 FC2 旧缓存）
for (let i = localStorage.length - 1; i >= 0; i--) {
  const key = localStorage.key(i);
  if (key && key.startsWith(LS_PREFIX)) {
    const av = key.slice(LS_PREFIX.length);
    const val = localStorage.getItem(key);
    // 清理旧格式 URL 和 FC2 番号旧缓存（之前可能缓存了 null）
    if (val && val.startsWith("http://10.0.0.235:9090")) {
      localStorage.removeItem(key);
    } else if (av.toLowerCase().startsWith("fc2") && val === "null") {
      localStorage.removeItem(key);
    } else if (val && val !== "null") {
      posterCache.set(av, val);
    }
  }
}

function _normalizeAvCode(code) {
  const lower = code.toLowerCase();
  if (lower.startsWith("fc2")) {
    // FC2番号统一映射为 fc2-数字 格式
    // FC2PPV-4907804 → fc2-4907804
    // FC2-PPV-4907804 → fc2-4907804
    // FC2-4907804 → fc2-4907804
    let m = lower.match(/fc2-?ppv-?(\d+)/);
    if (m) return `fc2-${m[1]}`;
    m = lower.match(/fc2-?(\d+)/);
    if (m) return `fc2-${m[1]}`;
    return lower;
  }
  const dashIdx = lower.indexOf("-");
  if (dashIdx === -1) return lower;
  const prefix = lower.slice(0, dashIdx).replace(/^\d+/, "");
  return (prefix || lower.slice(0, dashIdx)) + lower.slice(dashIdx);
}

async function _searchDbo(q) {
  const r = await fetch("/api/dbo-search?q=" + encodeURIComponent(q) + "&limit=1");
  const data = await r.json();
  return (data.success && data.data.movies.length > 0) ? data.data.movies : null;
}

async function _doFetch(av) {
  try {
    // 1) 精确匹配原始码
    let movies = await _searchDbo(av);
    // 2) 无结果则用规范化码回退（300Mium-1336 → mium-1336）
    if (!movies) {
      const normalized = _normalizeAvCode(av);
      if (normalized !== av.toLowerCase()) {
        movies = await _searchDbo(normalized);
      }
    }
    if (movies) {
      const match = movies.find(m => m.number === av) || movies[0];
      const remoteUrl = new URL(match.cover_url, DBO_BASE).searchParams.get("url");
      if (remoteUrl) {
        return "/api/poster-proxy?url=" + encodeURIComponent(remoteUrl);
      }
    }
  } catch (e) {
    console.error("Poster fetch error:", av, e);
  }
  return null;
}

const MAX_POSTER_CONCURRENCY = 4;
let posterInFlight = 0;

function _processQueue() {
  while (posterInFlight < MAX_POSTER_CONCURRENCY && posterQueue.length > 0) {
    const { av, resolve } = posterQueue.shift();
    posterInFlight++;
    _fetchOne(av, resolve);
  }
}

async function _fetchOne(av, resolve) {
  const url = await _doFetch(av);
  if (url) {
    posterCache.set(av, url);
    try { localStorage.setItem(LS_PREFIX + av, url); } catch (_) {}
  } else {
    posterCache.set(av, null);
  }
  resolve(url);
  posterInFlight--;
  _processQueue();
}

function fetchPoster(av) {
  if (posterCache.has(av)) return Promise.resolve(posterCache.get(av));
  if (pendingFetches.has(av)) return pendingFetches.get(av);
  const promise = new Promise((resolve) => {
    posterQueue.push({ av, resolve });
    _processQueue();
  });
  pendingFetches.set(av, promise);
  return promise;
}

async function loadPoster(el, av) {
  av = av.replace(/\.(mp4|mkv|avi|wmv|flv|mov|webm|ts|m4v)$/i, "");
  const url = await fetchPoster(av);
  pendingFetches.delete(av);
  const img = el.querySelector(".gallery-poster img");
  const poster = el.querySelector(".gallery-poster");
  if (url && img) {
    img.src = url;
  } else if (poster) {
    poster.classList.add("gallery-poster-failed");
  }
}

const _origLoadJobs = loadJobs;
let _lastTabHash = "";
let _lastGalleryHash = "";

loadJobs = async function() {
  try {
    const jobs = await api("/api/jobs");
    const tabHash = JSON.stringify(jobs.map(j => [j.id, j.status, j.message, j.progress, j.output_files, j.completed_at]));
    const galleryHash = JSON.stringify(jobs.filter(j => j.status === "done").map(j => [j.id, j.output_files, j.completed_at]));
    allJobs = jobs;

    if (tabHash !== _lastTabHash) {
      _lastTabHash = tabHash;
      renderTab(currentTab);
    }
    if (galleryHash !== _lastGalleryHash) {
      _lastGalleryHash = galleryHash;
      const gallery = $("#gallery");
      if (gallery) gallery.classList.add("no-animate");
      renderHome();
    }
  } catch (e) {
    console.error(e);
  } finally {
    hideSplash();
  }
};
loadJobs().catch(console.error);
setInterval(loadJobs, 5000);

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});




/* ═══ NAVIGATION ═══ */
function switchView(viewId) {
  document.querySelectorAll(".dock-item, .dock-mobile-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewId);
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const view = document.getElementById("view-" + viewId);
  if (view) view.classList.add("active");
  if (viewId === "queue") renderTab(currentTab);
  if (viewId === "config") loadConfig().catch(() => {});
  if (viewId === "home") {
    const gallery = $("#gallery");
    if (gallery) gallery.classList.remove("no-animate");
    renderHome();
  }
}

document.querySelectorAll(".dock-item, .dock-mobile-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

/* ═══ PACK DOWNLOAD ═══ */
function downloadPack(ts) {
  const a = document.createElement("a");
  a.href = "/api/pack?date=" + Math.floor(ts / 1000);
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ═══ HOME GALLERY — 按日期归组 ═══ */
function renderHome() {
  const gallery = $("#gallery");
  if (!gallery) return;

  const done = allJobs.filter((j) => j.status === "done" && (j.output_files || []).length > 0);
  const sorted = done.sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0));

  const count = $("#home-count");
  if (count) count.textContent = done.length + " 部已完成";

  if (sorted.length === 0) {
    gallery.innerHTML = '<div class="gallery-empty">尚无已完成字幕</div>';
    return;
  }

  // 收集已有卡片的 DOM，按 av 号索引（用于恢复已加载的海报）
  const existingCards = new Map();
  gallery.querySelectorAll(".gallery-card").forEach((el) => {
    const av = el.dataset.av;
    if (av) existingCards.set(av, el);
  });

  // 按日期分组
  const nowTs = Date.now();
  const today = new Date(new Date().toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" })).getTime();
  const yesterday = today - 86400000;

  const groups = new Map();
  sorted.forEach((job) => {
    const ts = (job.completed_at || 0) * 1000;
    const d = new Date(ts);
    const dateStart = new Date(d.toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" })).getTime();
    const key = dateStart;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(job);
  });

  // 构建 HTML
  let html = "";
  for (const [ts, jobs] of groups) {
    // 日期标题
    let label;
    if (ts === today) {
      label = "今天";
    } else if (ts === yesterday) {
      label = "昨天";
    } else {
      const d = new Date(ts);
      const now = new Date();
      if (d.getFullYear() === now.getFullYear()) {
        label = (d.getMonth() + 1) + "月" + d.getDate() + "日";
      } else {
        label = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
      }
    }
    html += '<div class="gallery-section"><h3 class="gallery-section-header"><span>' + escapeHtml(label) + '</span><button class="pack-btn" onclick="downloadPack(' + ts + ')">打包(' + jobs.length + ')</button></h3><div class="gallery-row">';
    for (const job of jobs) {
      // 优先从 output_files 提取 av 码（更可靠），否则从 input_path 提取
      let av = "";
      if (job.output_files && job.output_files.length > 0) {
        // output_files 格式: ["/output/FNS-192.srt"]
        const filename = job.output_files[0].split("/").pop() || "";
        av = filename.replace(/\.(srt|vtt|ass|ssa|sub|txt)$/i, "");
      }
      if (!av) {
        av = (job.input_path.split("/").pop() || job.input_path).replace(/\.(mp4|mkv|avi|wmv|flv|mov|webm|ts|m4v)$/i, "");
      }
      const fmt = ((job.output_files || [])[0] || "").split(".").pop() || "srt";
      html +=
        '<div class="gallery-card" data-job-id="' + escapeHtml(job.id) + '" data-av="' + escapeHtml(av) + '">' +
        '<div class="gallery-poster"><img alt="' + escapeHtml(av) + '" loading="lazy" /></div>' +
        '<div class="gallery-poster-fallback">' + escapeHtml(av) + '</div>' +
        '<div class="gallery-footer">' +
        '<div class="av">' + escapeHtml(av) + '</div>' +
        '<div class="meta">' + escapeHtml(fmtDate(job.completed_at)) + '</div>' +
        '<span class="fmt-badge">' + escapeHtml(fmt) + '</span>' +
        '</div></div>';
    }
    html += '</div></div>';
  }

  // 保存各日期行的滚动位置
  const scrollPositions = [];
  gallery.querySelectorAll(".gallery-row").forEach((row) => {
    scrollPositions.push({ date: row.closest(".gallery-section")?.querySelector(".gallery-section-header")?.textContent || "", left: row.scrollLeft });
  });

  gallery.innerHTML = html;

  // 恢复滚动位置
  gallery.querySelectorAll(".gallery-row").forEach((row) => {
    const header = row.closest(".gallery-section")?.querySelector(".gallery-section-header")?.textContent || "";
    const saved = scrollPositions.find((s) => s.date === header);
    if (saved) row.scrollLeft = saved.left;
  });

  // 恢复已加载的海报图片 src
  for (const [av, oldCard] of existingCards) {
    const oldImg = oldCard.querySelector(".gallery-poster img");
    if (!oldImg || !oldImg.src) continue;
    const newCard = gallery.querySelector('.gallery-card[data-av="' + av + '"]');
    if (newCard) {
      const newImg = newCard.querySelector(".gallery-poster img");
      if (newImg) newImg.src = oldImg.src;
    }
  }

  // 异步加载海报
  gallery.querySelectorAll(".gallery-card").forEach((card) => {
    const img = card.querySelector(".gallery-poster img");
    if (img.src) return;
    const av = card.dataset.av;
    if (av) loadPoster(card, av);
  });
}




/* ═══ SPLASH ═══ */
function hideSplash() {
  const splash = document.getElementById("splash");
  if (splash) splash.classList.add("is-hidden");
}

// 保底：3 秒后无论是否加载完成都隐藏 splash
setTimeout(hideSplash, 3000);

/* ═══ THEME TOGGLE ═══ */
function setTheme(theme) {
  const root = document.documentElement;
  document.getElementById("theme-toggle-mobile");
  if (theme === "light") {
    root.classList.add("light");
  } else {
    root.classList.remove("light");
  }
  localStorage.setItem("subtitle-theme", theme);
}

function toggleTheme() {
  const isLight = document.documentElement.classList.contains("light");
  setTheme(isLight ? "dark" : "light");
}

// Restore saved theme
const saved = localStorage.getItem("subtitle-theme");
if (saved) setTheme(saved);

document.getElementById("theme-toggle")?.addEventListener("click", toggleTheme);
document.getElementById("theme-toggle-mobile")?.addEventListener("click", toggleTheme);


