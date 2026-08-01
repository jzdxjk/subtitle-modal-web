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

function queueMatchesSearch(job, query) {
  if (!query) return true;
  const haystack = [
    job.id,
    job.input_path,
    job.message,
    job.status,
    job.output_dir,
    ...(job.output_files || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return "";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}m${r}s`;
}

function fmtDurationClock(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function fmtFileSize(bytes) {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return "--";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(2)} ${units[unit]}`;
}

function elapsedSeconds(startedAt) {
  if (!startedAt || startedAt === 0) return 0;
  return Math.floor(Date.now() / 1000 - startedAt);
}

function livePhaseSeconds(job, kind) {
  const baseSeconds = Number(job[`${kind}_seconds`] || 0);
  const phaseStartedAt = Number(job.phase_started_at || 0);
  if (job.phase !== kind || !phaseStartedAt) return baseSeconds;
  return baseSeconds + elapsedSeconds(phaseStartedAt);
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

function updateRunningTimers() {
  document.querySelectorAll('.elapsed-timer').forEach(el => {
    const kind = el.dataset.timerKind || "total";
    const startedAt = parseFloat(el.dataset.startedAt);
    const baseSeconds = Number(el.dataset.baseSeconds || 0);
    const phase = el.dataset.phase || "";
    const phaseStartedAt = parseFloat(el.dataset.phaseStartedAt || 0);
    const livePhase = kind === "local" ? phase === "local" : kind === "cloud" ? phase === "cloud" : false;
    if (phase === "waiting_local") {
      el.textContent = "--:--";
      return;
    }
    if (kind === "total" && !startedAt && !baseSeconds) {
      el.textContent = "--:--";
      return;
    }
    const value = kind === "total" ? (startedAt ? elapsedSeconds(startedAt) : baseSeconds) : livePhaseSeconds({
      phase: livePhase ? kind : phase,
      phase_started_at: phaseStartedAt,
      [`${kind}_seconds`]: baseSeconds,
    }, kind);
    el.textContent = fmtDurationClock(value);
  });
}

function formatRangeValue(input, mode) {
  const value = Number(input.value || 0);
  if (mode === "minutes") return String(Math.round(value / 60));
  if (mode === "seconds") return `${value}s`;
  return String(value);
}

function syncRangeControl(control) {
  const input = control.querySelector('input[type="range"]');
  if (!input) return;
  const valueEl = control.querySelector("[data-range-value]");
  const min = Number(input.min || 0);
  const max = Number(input.max || 100);
  const value = Number(input.value || min);
  const percent = max === min ? 0 : ((value - min) / (max - min)) * 100;
  input.style.setProperty("--percent", `${Math.max(0, Math.min(100, percent))}%`);
  if (valueEl) valueEl.textContent = formatRangeValue(input, control.dataset.display || "raw");
}

function initRangeControls() {
  document.querySelectorAll("[data-range-control]").forEach((control) => {
    const input = control.querySelector('input[type="range"]');
    if (!input) return;
    syncRangeControl(control);
    if (input.dataset.rangeBound === "true") return;
    input.dataset.rangeBound = "true";
    input.addEventListener("input", () => syncRangeControl(control));
  });
}


async function loadConfig() {
  const config = await api("/api/config");
  if (config.repo_branch === "bec3d22") config.repo_branch = "v1.7";
  for (const [key, value] of Object.entries(config)) {
    const input = document.querySelector(`[name="${key}"]`);
    if (!input) continue;
    if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else if (input.tagName === "SELECT") {
      if (value != null && ![...input.options].some((o) => o.value === value)) {
        input.appendChild(new Option(value, value));
      }
      if (value != null && !String(value).includes("***")) {
        input.value = value;
      }
    } else if (value != null && !String(value).includes("***")) {
      input.value = value;
    }
  }
  DBO_BASE = config.metadata_provider === "javdb" ? config.javdb_api_url : config.dbo_api_url;
  if (config.dbo_api_key) DBO_KEY = config.dbo_api_key;
  const activeApiUrl = config.metadata_provider === "javdb" ? config.javdb_api_url : config.dbo_api_url;
  const activeApiInput = $("#metadata-api-url");
  if (activeApiInput) activeApiInput.value = activeApiUrl || "";
  initRangeControls();
  $("#config-status").textContent = JSON.stringify(config, null, 2);
}

let metadataNodes = [];

function latencyLabel(latency) {
  if (latency == null) return { text: "--", tone: "unknown" };
  if (latency < 500) return { text: `${latency} ms  良`, tone: "good" };
  if (latency < 1200) return { text: `${latency} ms  慢`, tone: "slow" };
  return { text: `${latency} ms  极慢`, tone: "bad" };
}

function renderMetadataNodes(nodes) {
  metadataNodes = nodes || [];
  const list = $("#metadata-node-list");
  if (!list) return;
  list.innerHTML = metadataNodes.map((node) => {
    const latency = latencyLabel(node.latency_ms);
    const statusClass = node.ok === true ? "online" : node.ok === false ? "offline" : "pending";
    const statusTitle = node.error ? ` title="${escapeHtml(node.error)}"` : "";
    return `<button type="button" class="metadata-node-row${node.current ? " current" : ""}" data-node-id="${escapeHtml(node.id)}">
      <span class="metadata-node-status ${statusClass}"${statusTitle}></span>
      <span class="metadata-node-name"><strong>${escapeHtml(node.name)}</strong>${node.current ? '<em><span class="material-symbols-outlined">check</span>当前</em>' : ""}</span>
      <code>${escapeHtml(node.url || "未配置")}</code>
      <span class="metadata-node-ip">${escapeHtml(node.ip || "--")}</span>
      <span class="metadata-node-latency ${latency.tone}">${latency.text}</span>
      <span class="metadata-node-probe material-symbols-outlined" data-probe-node="${escapeHtml(node.id)}" title="重新探测">refresh</span>
    </button>`;
  }).join("");
}

async function loadMetadataNodes(probe = false) {
  const path = probe ? "/api/metadata-nodes/probe" : "/api/metadata-nodes";
  const data = probe ? await api(path, { method: "POST" }) : await api("/api/metadata-nodes");
  renderMetadataNodes(data.nodes || []);
}

async function selectMetadataNode(nodeId) {
  if (nodeId === "dbo") {
    const dboUrl = document.querySelector('[name="dbo_api_url"]').value.trim();
    const dboKey = document.querySelector('[name="dbo_api_key"]').value.trim();
    if (!dboUrl) throw new Error("请先填写 DBO API 地址");
    const payload = { dbo_api_url: dboUrl };
    if (dboKey) payload.dbo_api_key = dboKey;
    await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
  }
  const saved = await api("/api/metadata-nodes/select", {
    method: "POST",
    body: JSON.stringify({ node_id: nodeId }),
  });
  document.querySelector('[name="metadata_provider"]').value = saved.metadata_provider;
  document.querySelector('[name="javdb_api_url"]').value = saved.javdb_api_url;
  DBO_BASE = saved.metadata_provider === "javdb" ? saved.javdb_api_url : saved.dbo_api_url;
  $("#metadata-api-url").value = DBO_BASE || "";
  localStorage.removeItem("poster_provider_version");
  posterCache.clear();
  $("#metadata-node-dialog").close();
  showToast(`已切换到 ${nodeId === "dbo" ? "DBO" : "JavDB"} 节点`);
}

$("#choose-metadata-node")?.addEventListener("click", async () => {
  const dialog = $("#metadata-node-dialog");
  dialog.showModal();
  renderMetadataNodes([{ id: "loading", name: "正在加载节点", url: "", current: false }]);
  try {
    await loadMetadataNodes(false);
    await loadMetadataNodes(true);
  } catch (error) {
    showToast("节点探测失败: " + error.message, false);
  }
});

$("#close-metadata-dialog")?.addEventListener("click", () => $("#metadata-node-dialog").close());
$("#metadata-node-dialog")?.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
$("#probe-all-metadata-nodes")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await loadMetadataNodes(true);
  } catch (error) {
    showToast(error.message, false);
  } finally {
    button.disabled = false;
  }
});
$("#metadata-node-list")?.addEventListener("click", async (event) => {
  const probe = event.target.closest("[data-probe-node]");
  const row = event.target.closest(".metadata-node-row");
  if (!row || row.dataset.nodeId === "loading") return;
  try {
    if (probe) {
      event.stopPropagation();
      const updated = await api(`/api/metadata-nodes/${encodeURIComponent(probe.dataset.probeNode)}/probe`, { method: "POST" });
      renderMetadataNodes(metadataNodes.map((node) => node.id === updated.id ? updated : node));
      return;
    }
    await selectMetadataNode(row.dataset.nodeId);
  } catch (error) {
    showToast(error.message, false);
  }
});

let modalAccounts = [];
let activeModalAccountId = "";

function renderModalAccount() {
  const select = $("#modal-account-select");
  const account = modalAccounts.find((item) => item.id === activeModalAccountId);
  if (select) {
    select.innerHTML = modalAccounts.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("");
    select.value = activeModalAccountId;
  }
  $("#modal-account-name").value = account?.name || "";
  $("#modal-account-token-id").value = "";
  $("#modal-account-token-secret").value = "";
  $("#modal-account-hf-token").value = "";
  const avatar = $("#topbar-avatar");
  if (avatar) avatar.textContent = [...(account?.name || "M")].find((char) => char.trim()) || "M";
}

async function loadModalAccounts() {
  const data = await api("/api/modal-accounts");
  modalAccounts = data.accounts || [];
  activeModalAccountId = data.active_account_id || "";
  renderModalAccount();
}

$("#modal-account-select")?.addEventListener("change", async (event) => {
  try {
    await api(`/api/modal-accounts/${encodeURIComponent(event.target.value)}/activate`, { method: "POST" });
    activeModalAccountId = event.target.value;
    renderModalAccount();
    showToast("已切换 Modal 账户");
  } catch (error) {
    renderModalAccount();
    showToast(error.message, false);
  }
});

$("#modal-account-new")?.addEventListener("click", () => {
  activeModalAccountId = "";
  $("#modal-account-name").value = "";
  $("#modal-account-token-id").value = "";
  $("#modal-account-token-secret").value = "";
  $("#modal-account-hf-token").value = "";
});

$("#modal-account-save")?.addEventListener("click", async () => {
  const name = $("#modal-account-name").value.trim();
  if (!name) return showToast("请填写账户名称", false);
  try {
    const saved = await api("/api/modal-accounts", { method: "POST", body: JSON.stringify({ id: activeModalAccountId || null, name, token_id: $("#modal-account-token-id").value.trim(), token_secret: $("#modal-account-token-secret").value.trim(), hf_token: $("#modal-account-hf-token").value.trim() }) });
    modalAccounts = saved.modal_accounts || [];
    activeModalAccountId = saved.active_modal_account_id || "";
    renderModalAccount();
    showToast("Modal 账户已保存");
  } catch (error) {
    showToast(error.message, false);
  }
});

$("#modal-account-delete")?.addEventListener("click", async () => {
  if (!activeModalAccountId || !confirm("确定删除当前 Modal 账户？")) return;
  try {
    const saved = await api(`/api/modal-accounts/${encodeURIComponent(activeModalAccountId)}`, { method: "DELETE" });
    modalAccounts = saved.modal_accounts || [];
    activeModalAccountId = saved.active_modal_account_id || "";
    renderModalAccount();
  } catch (error) {
    showToast(error.message, false);
  }
});

$("#modal-monthly-cost")?.addEventListener("click", async () => {
  try {
    const result = await api("/api/modal-cost/month");
    showToast(`本月累计 $${Number(result.cost || 0).toFixed(2)}`);
  } catch (error) {
    showToast(error.message, false);
  }
});

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

function renderJobRow(job) {
  const retryable = job.status === "failed" || job.status === "cancelled" || job.status === "cancelling";
  const statusLabel = STATUS_LABELS[job.status] || job.status;
  const isRunning = job.status === "running";
  const isQueued = job.status === "queued";
  const isFailed = job.status === "failed";
  const isDone = job.status === "done";
  const isCancelled = job.status === "cancelled" || job.status === "cancelling";
  const isCancelling = job.status === "cancelling";
  const avCode = extractAvCode(job.input_path || "");
  const shortId = avCode || `#${String(job.id).slice(0, 8).toUpperCase()}`;
  const fileSize = fmtFileSize(job.input_size_bytes);
  const queueTone = isRunning ? "running" : isQueued ? "queued" : isFailed ? "failed" : isDone ? "done" : isCancelled ? "cancelled" : job.status;

  const startedAt = Number(job.started_at || 0);
  const completedAt = job.completed_at || 0;
  const durationSeconds = isRunning && startedAt
    ? elapsedSeconds(startedAt)
    : completedAt && startedAt
      ? Math.max(0, completedAt - startedAt)
      : 0;
  const localBaseSeconds = Number(job.local_seconds || 0);
  const cloudBaseSeconds = Number(job.cloud_seconds || 0);
  const localSeconds = livePhaseSeconds(job, "local");
  const cloudSeconds = livePhaseSeconds(job, "cloud");
  const displayTime = durationSeconds ? fmtDurationClock(durationSeconds) : "--:--";
  const localTime = durationSeconds ? fmtDurationClock(localSeconds) : "--:--";
  const cloudTime = durationSeconds ? fmtDurationClock(cloudSeconds) : "--:--";
  const completedAtText = completedAt ? `${fmtDate(completedAt)} ${fmtClock(completedAt)}` : "--";

  const phaseLabels = {
    waiting_local: "等待本地处理",
    local: "本地抽音频中",
    uploading: "上传云端中",
    submitting: "提交云端中",
    cloud: "云端 GPU 转录中",
    finalizing: "整理字幕中",
    translating: "翻译字幕中",
    moving: "移动源文件中",
  };
  const statusText = isRunning ? (phaseLabels[job.phase] || "运行中") : statusLabel;
  const statusDetail = isFailed && job.message ? `<p class="job-status-detail">错误原因: ${escapeHtml(job.message)}</p>` : "";

  let progressHtml = '';
  if (job.phase !== "waiting_local" && job.progress > 0 && (job.status === "running" || job.status === "cancelling")) {
    let phaseClass = "progress-local";
    if (job.progress >= 90) phaseClass = "progress-final";
    else if (job.progress >= 40) phaseClass = "progress-cloud";
    progressHtml = `
      <div class="job-progress-line">
        <div class="progress-bar"><div class="progress-fill ${phaseClass}" style="width:${Math.min(job.progress, 100)}%"></div></div>
        <span class="job-progress-percent">${Math.min(job.progress, 100)}%</span>
      </div>
    `;
  }

  const actions = [];
  if (isRunning || isQueued || isCancelling) {
    actions.push(`<button class="cancel-btn job-action" data-id="${job.id}" title="取消"><span class="material-symbols-outlined">stop_circle</span></button>`);
  } else if (isFailed || job.status === "cancelled" || retryable) {
    const retryLabel = job.status === "cancelled" ? "重新加入" : "重试";
    actions.push(`<button class="retry-btn job-action" data-id="${job.id}" title="${retryLabel}"><span class="material-symbols-outlined">refresh</span><span>${retryLabel}</span></button>`);
  }
  if (!isRunning && !isQueued && !isCancelling && !isDone) {
    actions.push(`<button class="delete-btn job-action" data-id="${job.id}" title="删除"><span class="material-symbols-outlined">delete</span></button>`);
  }

  return `
    <article class="job job-row ${escapeHtml(job.status)}" data-status="${escapeHtml(queueTone)}">
      <div class="job-row-main">
        <div class="job-row-left">
          <span class="job-id">${escapeHtml(shortId)}</span>
        </div>
        <span class="job-size">${escapeHtml(fileSize)}</span>
        ${isDone ? `
          <div class="job-completed-total"><span class="job-duration">${escapeHtml(displayTime)}</span></div>
          <div class="job-completed-phases">
            <span class="job-time-detail"><span class="material-symbols-outlined">laptop_mac</span>${escapeHtml(localTime)}</span>
            <span class="job-time-detail"><span class="material-symbols-outlined">cloud</span>${escapeHtml(cloudTime)}</span>
          </div>
          <time class="job-completed-at" datetime="${completedAt ? new Date(completedAt * 1000).toISOString() : ""}">${escapeHtml(completedAtText)}</time>
        ` : `
          <div class="job-row-center">
            <div class="job-status-meta">
              <div class="job-status-line ${escapeHtml(queueTone)}">
                <span class="job-status-dot"></span>
                <span>${escapeHtml(statusText)}</span>
              </div>
              <span class="job-size-mobile">${escapeHtml(fileSize)}</span>
            </div>
            ${progressHtml}
            ${statusDetail}
            ${!isRunning && !isQueued && !isFailed && !isCancelled ? `<p class="job-msg">${escapeHtml(job.message || "")}</p>` : ""}
          </div>
          <div class="job-time-block">
            <span class="job-duration elapsed-timer" data-timer-kind="total" data-started-at="${isRunning ? startedAt : ""}" data-base-seconds="${durationSeconds}" data-phase="${escapeHtml(job.phase || "")}">${escapeHtml(displayTime)}</span>
            <span class="job-time-detail"><span class="material-symbols-outlined">laptop_mac</span><span class="elapsed-timer" data-timer-kind="local" data-base-seconds="${localBaseSeconds}" data-phase="${escapeHtml(job.phase || "")}" data-phase-started-at="${job.phase_started_at || 0}">${escapeHtml(localTime)}</span></span>
            <span class="job-time-detail"><span class="material-symbols-outlined">cloud</span><span class="elapsed-timer" data-timer-kind="cloud" data-base-seconds="${cloudBaseSeconds}" data-phase="${escapeHtml(job.phase || "")}" data-phase-started-at="${job.phase_started_at || 0}">${escapeHtml(cloudTime)}</span></span>
          </div>
          ${actions.length ? `<div class="job-actions">${actions.join("")}</div>` : ""}
        `}
      </div>
    </article>
  `;
}

function renderJobCard(job) {
  return renderJobRow(job);
}

async function loadJobs() {
  allJobs = await api("/api/jobs");
  renderTab(currentTab);
}

function getQueueJobs(tab) {
  const filtered = allJobs.filter((j) => TABS[tab].statuses.includes(j.status));
  if (tab === "queued") {
    return filtered.sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
  }
  if (tab === "running") {
    return filtered.sort((a, b) => {
      const aStarted = Number(a.started_at || 0);
      const bStarted = Number(b.started_at || 0);
      if (Boolean(aStarted) !== Boolean(bStarted)) return aStarted ? -1 : 1;
      if (aStarted && bStarted && aStarted !== bStarted) return aStarted - bStarted;
      return (a.created_at || 0) - (b.created_at || 0);
    });
  }
  return filtered;
}

function getJobsForTab(tab) {
  return getQueueJobs(tab);
}

function renderPager(pagerEl, page, totalPages, tab) {
  if (!pagerEl) return;
  if (totalPages <= 1) {
    pagerEl.innerHTML = "";
    return;
  }
  const buttons = [];
  const start = Math.max(1, page - 1);
  const end = Math.min(totalPages, page + 1);
  buttons.push(`<button type="button" data-action="prev" ${page <= 1 ? "disabled" : ""}><span class="material-symbols-outlined">chevron_left</span></button>`);
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) {
      buttons.push(`<button type="button" data-page="${i}" class="${i === page ? "active" : ""}">${i}</button>`);
    }
  } else {
    if (start > 1) buttons.push(`<button type="button" data-page="1">1</button>`);
    if (start > 2) buttons.push(`<span class="pager-ellipsis">&hellip;</span>`);
    for (let i = start; i <= end; i++) {
      buttons.push(`<button type="button" data-page="${i}" class="${i === page ? "active" : ""}">${i}</button>`);
    }
    if (end < totalPages - 1) buttons.push(`<span class="pager-ellipsis">&hellip;</span>`);
    if (end < totalPages) buttons.push(`<button type="button" data-page="${totalPages}">${totalPages}</button>`);
  }
  buttons.push(`<button type="button" data-action="next" ${page >= totalPages ? "disabled" : ""}><span class="material-symbols-outlined">chevron_right</span></button>`);
  pagerEl.innerHTML = `<div class="pager-shell">${buttons.join("")}</div>`;
  pagerEl.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.action === "prev" && page > 1) pageByTab[tab] = page - 1;
      else if (btn.dataset.action === "next" && page < totalPages) pageByTab[tab] = page + 1;
      else if (btn.dataset.page) pageByTab[tab] = Number(btn.dataset.page);
      renderTab(tab);
    });
  });
}

function renderTab(tab) {
  const tabJobs = getQueueJobs(tab);
  const totalPages = Math.ceil(tabJobs.length / PAGE_SIZE) || 1;
  let page = pageByTab[tab];
  if (page > totalPages) page = totalPages;
  pageByTab[tab] = page;
  const start = (page - 1) * PAGE_SIZE;
  const pageJobs = tabJobs.slice(start, start + PAGE_SIZE);

  const listHead = $(".queue-list-head");
  if (listHead) {
    const headers = tab === "completed"
      ? ["番号", "大小", "总耗时", "本地 / 云端", "完成时间"]
      : ["番号", "大小", "状态 / 进度", "耗时", "操作"];
    listHead.classList.toggle("completed", tab === "completed");
    listHead.innerHTML = headers.map((header) => `<span>${header}</span>`).join("");
  }

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const t = btn.dataset.tab;
    const count = getQueueJobs(t).length;
    btn.textContent = `${TABS[t].label} (${count})`;
    btn.classList.toggle("active", t === currentTab);
  });

  const failedTools = $("#failed-tools");
  const failedToolsText = $("#failed-tools-text");
  if (failedTools && failedToolsText) {
    const failedCount = getQueueJobs("failed").length;
    failedToolsText.textContent = `当前有 ${failedCount} 个失败任务`;
    failedTools.classList.toggle("hidden", tab !== "failed");
  }

  document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
  const pane = document.getElementById("tab-" + tab);
  if (pane) pane.classList.add("active");

  const jobsEl = pane ? pane.querySelector(".jobs") : null;
  if (jobsEl) {
    jobsEl.innerHTML = pageJobs.map(renderJobCard).join("") || '<p class="empty">暂无任务</p>';
  }

  document.querySelectorAll(".cancel-btn[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => cancelJob(btn.dataset.id));
  });

  document.querySelectorAll(".retry-btn[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => retryJob(btn.dataset.id));
  });

  document.querySelectorAll(".delete-btn[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => deleteJob(btn.dataset.id));
  });

  const pagerEl = pane ? pane.querySelector(".pager") : null;
  renderPager(pagerEl, page, totalPages, tab);
}
function switchTab(tab) {
  currentTab = tab;
  renderTab(tab);
}

$("#config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.target);
  data.min_file_size_mb = Number(data.min_file_size_mb || 0);
  data.default_timeout_seconds = Number(data.default_timeout_seconds || 7200);
  data.watchdog_interval_seconds = Number(data.watchdog_interval_seconds || 60);
  data.max_workers = Number(data.max_workers || 1);
  data.enable_watchdog = Boolean(event.target.enable_watchdog?.checked);
  data.enable_smart_vad = Boolean(event.target.enable_smart_vad.checked);
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

/* ═══ TRANSCRIBE ═══ */

async function loadTranscribeConfig() {
  const config = await api("/api/config");
  const f = document.forms["transcribe-form"];
  if (!f) return;
  f.enable_transcribe.checked = !!config.enable_transcribe;
  f.openai_api_url.value = config.openai_api_url || "";
  f.openai_api_key.value = config.openai_api_key || "";
  if (config.openai_model) {
    const sel = f.openai_model;
    if (![...sel.options].some(o => o.value === config.openai_model)) {
      sel.appendChild(new Option(config.openai_model, config.openai_model));
    }
    sel.value = config.openai_model;
  }
  f.transcribe_prompt.value = config.transcribe_prompt || "";
  if (config.transcribe_model) f.transcribe_model.value = config.transcribe_model;
}

$("#transcribe-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const f = event.target;
  const data = {
    enable_transcribe: f.enable_transcribe.checked,
    openai_api_url: f.openai_api_url.value.trim() || null,
    openai_api_key: f.openai_api_key.value.trim() || null,
    openai_model: f.openai_model.value || null,
    transcribe_prompt: f.transcribe_prompt.value || null,
    transcribe_model: f.transcribe_model.value || null,
  };
  try {
    await api("/api/transcribe-config", { method: "POST", body: JSON.stringify(data) });
    showToast("✅ 转录配置已保存");
  } catch (error) {
    showToast("保存失败: " + error.message, false);
  }
});

$("#fetch-models-btn")?.addEventListener("click", async () => {
  const btn = $("#fetch-models-btn");
  const sel = $("#openai-model-select");
  btn.disabled = true; btn.textContent = "获取中...";
  try {
    const r = await api("/api/transcribe/models", { method: "POST" });
    sel.innerHTML = "";
    r.models.forEach(m => { sel.appendChild(new Option(m, m)); });
    btn.textContent = "✅ " + r.models.length + " 个";
    showToast("获取到 " + r.models.length + " 个模型");
  } catch (e) {
    btn.textContent = "获取失败";
    showToast(e.message, false);
  } finally {
    btn.disabled = false;
  }
});

$("#test-openai-btn")?.addEventListener("click", async () => {
  const btn = $("#test-openai-btn");
  btn.disabled = true; btn.textContent = "检测中...";
  try {
    const r = await api("/api/transcribe/test", { method: "POST" });
    if (r.ok) btn.textContent = "✅ 连通 " + r.latency_ms + "ms (" + r.model + ")";
    else btn.textContent = "❌ " + (r.error || "失败");
  } catch (e) {
    btn.textContent = "❌ " + e.message.slice(0, 30);
  } finally {
    btn.disabled = false;
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
api("/api/version").then(r => { const v = $("#version"); if (v) v.textContent = r.version || "v3.02"; });

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
loadModalAccounts().catch((error) => showToast(error.message, false));

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

// 从文件名中提取 AV 番号（与后端 extract_av_code 保持一致），
// 能正确处理 MOON-058.zh.srt → MOON-058
const _AV_RE = /FC2-?(?:[A-Z]{3}-?)?\d{5,7}|(?:\d+)?[A-Z]{2,5}-\d{3,5}/i;
function extractAvCode(filename) {
  const m = filename.match(_AV_RE);
  return m ? m[0].toUpperCase() : "";
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
      const coverUrl = match.cover_url || match.thumb_url;
      const parsedUrl = new URL(coverUrl, DBO_BASE || window.location.origin);
      const remoteUrl = parsedUrl.searchParams.get("url") || parsedUrl.href;
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
  av = extractAvCode(av);
  if (!av) { av = el.dataset.av || ""; }
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
let galleryPageIndex = 0;

loadJobs = async function() {
  try {
    const jobs = await api("/api/jobs");
    const statusCounts = {};
    let progressSum = 0;
    for (const j of jobs) { statusCounts[j.status] = (statusCounts[j.status] || 0) + 1; progressSum += j.progress || 0; }
    const msgHash = jobs.filter(j => j.status === 'running').map(j => j.message).join('|');
    const tabHash = JSON.stringify(statusCounts) + "|" + progressSum + "|" + msgHash + "|" + (jobs[0]?.id || "");
    const doneJobs = jobs.filter(j => j.status === "done" && (j.output_files || []).length > 0);
    const galleryHash = doneJobs.length + "|" + (doneJobs[0]?.id || "") + "|" + (doneJobs[0]?.completed_at || "");
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
let _pollTimer = null;
let _elapsedTimer = null;

function startQueuePolling() {
  stopQueuePolling();
  _pollTimer = setInterval(loadJobs, 1000);
  _elapsedTimer = setInterval(updateRunningTimers, 1000);
}

function stopQueuePolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
}

startQueuePolling();

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

initRangeControls();




/* ═══ NAVIGATION ═══ */
function switchView(viewId) {
  document.querySelectorAll(".dock-item, .dock-mobile-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewId);
  });
  localStorage.setItem("subtitle-active-view", viewId);
  document.body.dataset.view = viewId;
  const heading = document.getElementById("topbar-heading");
  const headingTitle = heading ? heading.querySelector(".topbar-title-text") : null;
  if (headingTitle) headingTitle.textContent = "Subtitle Cloud";
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const view = document.getElementById("view-" + viewId);
  if (view) view.classList.add("active");
  if (viewId === "queue") { loadJobs().then(() => { renderTab(currentTab); startQueuePolling(); }); }
  else stopQueuePolling();
  if (viewId === "config") loadConfig().catch(() => {});
  if (viewId === "transcribe") loadTranscribeConfig().catch(() => {});
  if (viewId === "home") {
    const gallery = $("#gallery");
    if (gallery) gallery.classList.remove("no-animate");
    renderHome();
  }
}

document.querySelectorAll(".dock-item[data-view], .dock-mobile-item[data-view]").forEach((btn) => {
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

function downloadGalleryFile(jobId, fileIndex) {
  const a = document.createElement("a");
  a.href = "/api/jobs/" + encodeURIComponent(jobId) + "/download?file_index=" + fileIndex;
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

  // 按日期分组（全量）
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

  // 按天数分页：每页 5 个有海报的日期
  const allDates = [...groups.keys()].sort((a, b) => b - a);
  const daysPerPage = 5;
  const totalPages = Math.ceil(allDates.length / daysPerPage);
  if (galleryPageIndex >= totalPages) galleryPageIndex = Math.max(0, totalPages - 1);
  const pagedDates = allDates.slice(galleryPageIndex * daysPerPage, (galleryPageIndex + 1) * daysPerPage);

  // 构建 HTML
  let html = "";
  for (const ts of pagedDates) {
    const jobs = groups.get(ts);
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
    const fileCount = jobs.reduce((n, j) => n + (j.output_files || []).length, 0);
    html += '<div class="gallery-section"><h3 class="gallery-section-header"><span>' + escapeHtml(label) + '</span><button class="pack-btn" onclick="downloadPack(' + ts + ')">打包(' + fileCount + ')</button></h3><div class="gallery-row">';
    for (const job of jobs) {
      // 优先从 output_files 提取 av 码（更可靠），否则从 input_path 提取
      let av = "";
      if (job.output_files && job.output_files.length > 0) {
        const filename = job.output_files[0].split("/").pop() || "";
        av = extractAvCode(filename);
      }
      if (!av) {
        av = extractAvCode(job.input_path.split("/").pop() || job.input_path);
      }
      const fmt = ((job.output_files || [])[0] || "").split(".").pop() || "srt";
      html +=
        '<div class="gallery-card" data-job-id="' + escapeHtml(job.id) + '" data-av="' + escapeHtml(av) + '">' +
        '<div class="gallery-poster"><img alt="' + escapeHtml(av) + '" loading="lazy" /></div>' +
        '<div class="gallery-poster-fallback">' + escapeHtml(av) + '</div>' +
        '<div class="gallery-footer">' +
        '<div class="av">' + escapeHtml(av) + '</div>' +
        '<div class="meta">' + escapeHtml(fmtDate(job.completed_at)) + '</div>' +
        '<div class="gallery-actions"><span class="fmt-badge">' + escapeHtml(fmt) + '</span><button type="button" class="gallery-download" title="下载字幕" onclick="downloadGalleryFile(\'' + escapeHtml(job.id) + '\', 0)"><span class="material-symbols-outlined">download</span></button></div>' +
        '</div></div>';
    }
    html += '</div></div>';
  }

  // 页码导航
  if (totalPages > 1) {
    let pag = '<div class="gallery-pagination">';
    pag += '<button' + (galleryPageIndex === 0 ? ' disabled' : ' onclick="galleryPageIndex=0;renderHome();"') + '>«</button>';
    pag += '<button' + (galleryPageIndex === 0 ? ' disabled' : ' onclick="galleryPageIndex--;renderHome();"') + '>‹</button>';
    const start = Math.max(0, galleryPageIndex - 1);
    const end = Math.min(totalPages, galleryPageIndex + 2);
    for (let i = start; i < end; i++) {
      if (i === galleryPageIndex) {
        pag += '<button class="active" disabled>' + (i + 1) + '</button>';
      } else {
        pag += '<button onclick="galleryPageIndex=' + i + ';renderHome();">' + (i + 1) + '</button>';
      }
    }
    pag += '<button' + (galleryPageIndex >= totalPages - 1 ? ' disabled' : ' onclick="galleryPageIndex++;renderHome();"') + '>›</button>';
    pag += '<button' + (galleryPageIndex >= totalPages - 1 ? ' disabled' : ' onclick="galleryPageIndex=' + (totalPages - 1) + ';renderHome();"') + '>»</button>';
    pag += '</div>';
    html += pag;
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
  const normalized = theme === "dark" ? "dark" : "light";
  root.classList.toggle("dark", normalized === "dark");
  localStorage.setItem("subtitle-theme", normalized);
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.setAttribute("content", normalized === "dark" ? "#000000" : "#fcfcfc");
}

function toggleTheme() {
  const isDark = document.documentElement.classList.contains("dark");
  setTheme(isDark ? "light" : "dark");
}

// Stitch reference is light-themed; default to light for this dashboard.
const savedTheme = localStorage.getItem("subtitle-theme") || "light";
setTheme(savedTheme);

document.getElementById("theme-toggle")?.addEventListener("click", toggleTheme);
document.getElementById("theme-toggle-mobile")?.addEventListener("click", toggleTheme);

const initialView = localStorage.getItem("subtitle-active-view") || "home";
switchView(initialView);

