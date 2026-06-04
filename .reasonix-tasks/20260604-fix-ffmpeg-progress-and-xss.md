# 修复 ffmpeg 进度计算 bug + 前端 XSS 漏洞

> **执行指令：立即按下方改动指令修改代码，不要询问确认，不要分析讨论，直接 Edit/Write 文件。**

## 1. PROJECT_ROOT

`C:\Users\jzdxjk\Documents\字幕云翻译`

## 2. 上下文

两个 P0 问题：
1. ffmpeg 进度解析 bug：`_parse_ffmpeg_time` 将百分之一秒除以 10 而非 100，导致进度显示不准确
2. 前端 XSS 漏洞：所有 innerHTML 拼接未转义动态数据，可被注入恶意脚本

## 3. 参考实现

- `app/media.py:106-112` — `_parse_ffmpeg_time` 函数
- `app/static/app.js:161-177` — `renderJobCard` 函数（XSS 点）
- `app/static/app.js:575-596` — `renderHome` 函数（XSS 点）

## 4. 涉及文件

| 文件 | 改动类型 |
|---|---|
| `app/media.py` | 改 `_parse_ffmpeg_time` 的除数 |
| `app/static/app.js` | 添加 `escapeHtml` 函数，转义所有动态数据 |

## 5. 改动指令

### 5.1 `app/media.py` — `_parse_ffmpeg_time` 修复（line 111）

**Before**:
```python
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 10
```

**After**:
```python
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100
```

### 5.2 `app/static/app.js` — 添加 escapeHtml 工具函数

在文件开头（`const $ = ...` 之后，`async function api` 之前）插入：

```javascript
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
```

### 5.3 `app/static/app.js` — `renderJobCard` 转义（约 line 161-177）

**Before**:
```javascript
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
```

**After**:
```javascript
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
```

### 5.4 `app/static/app.js` — `renderHome` 转义（约 line 575-596）

**Before**:
```javascript
    html += '<div class="gallery-section"><h3 class="gallery-section-header"><span>' + label + '</span><button class="pack-btn" onclick="downloadPack(' + ts + ')">打包(' + jobs.length + ')</button></h3><div class="gallery-row">';
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
        '<div class="gallery-card" data-job-id="' + job.id + '" data-av="' + av + '">' +
        '<div class="gallery-poster"><img alt="' + av + '" loading="lazy" /></div>' +
        '<div class="gallery-poster-fallback">' + av + '</div>' +
        '<div class="gallery-footer">' +
        '<div class="av">' + av + '</div>' +
        '<div class="meta">' + fmtDate(job.completed_at) + '</div>' +
        '<span class="fmt-badge">' + fmt + '</span>' +
        '</div></div>';
    }
```

**After**:
```javascript
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
```

## 6. 完成判据（机器可验证）

1. `media.py:111` — `/10` 已改为 `/100`
2. `app.js` 文件开头存在 `escapeHtml` 函数定义
3. `renderJobCard` 中 `job.input_path`、`job.message`、`job.id`、`job.output_files` 均被 `escapeHtml()` 包裹
4. `renderHome` 中 `av`、`job.id`、`fmt`、`label` 均被 `escapeHtml()` 包裹
5. 现有测试全部通过：`cd tests && python -m pytest test_core.py -v`

## 7. 不得改动

- `app/worker.py` 不动
- `app/modal_runner.py` 不动
- `app/storage.py` 不动
- `app/config.py` 不动
- `Dockerfile` 不动
- `docker-compose.yml` 不动
- 其他文件不动
