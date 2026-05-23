const $ = (selector) => document.querySelector(selector);

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
    completedHtml = `<span class="completed-time">${label} ${fmtClock(job.completed_at)}</span>`;
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

  return `
    <article class="job ${job.status}">
      <div class="job-head">
        <strong>${statusLabel}</strong>
        <span>${job.id.slice(0, 8)}</span>
        ${timingHtml}
        <span class="head-spacer"></span>
        <div class="job-actions">${actions.join("")}</div>
      </div>
      ${progressHtml}
      <p class="job-path">${job.input_path}</p>
      <p class="job-msg">${job.message || ""}</p>
      ${completedHtml}
      <small>${(job.output_files || []).join("\n")}</small>
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
    $("#config-status").textContent = "✅ 保存配置成功！";
  } catch (error) {
    $("#config-status").textContent = error.message;
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

$("#refresh").addEventListener("click", loadJobs);
$("#retry-all-failed")?.addEventListener("click", retryAllFailedJobs);
loadConfig().catch((error) => $("#config-status").textContent = error.message);
loadJobs().catch(console.error);
setInterval(loadJobs, 5000);

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});


