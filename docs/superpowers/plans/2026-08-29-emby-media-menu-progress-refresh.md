# Emby 媒体菜单、任务进度与字幕完成刷新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为电影和单集视频提供 Emby 媒体菜单提交字幕任务、插件进度页轮询、完成后元数据刷新重试，以及可配置路径映射。

**Architecture:** 在现有 Emby 插件中增加视频媒体菜单 provider 与服务调用层；复用现有 `/api/plugin/jobs` 任务 API，在插件页内轮询并触发 Emby Item 刷新。路径映射在插件端完成，后端保留现有任务模型与刷新状态接口。

**Tech Stack:** C# netstandard2.0、Emby 4.8/4.9 server APIs、原生 HTML/CSS/JavaScript、Python FastAPI、pytest。

---

### Task 1: 建立路径映射与插件 API 的失败测试

**Files:**
- Modify: `tests/test_emby_plugin.py`
- Create: `emby-plugin/PathMapping.cs`

- [ ] **Step 1: Write failing tests**

在 `tests/test_emby_plugin.py` 增加纯 Python 对映射规则的契约测试：最长前缀优先、Windows 大小写不敏感、未匹配保留原路径、忽略空行和无 `=` 行。

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_emby_plugin.py -q`
Expected: FAIL，因为映射函数尚不存在。

- [ ] **Step 3: Implement minimal mapping helper**

在 C# `PathMapping.Apply(string path, string mappings)` 中按换行解析 `key=value`，按 key 长度降序匹配，使用 `OrdinalIgnoreCase`，拼接剩余相对路径并规范分隔符。

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_emby_plugin.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/test_emby_plugin.py emby-plugin/PathMapping.cs
git commit -m "test: define Emby path mapping contract"
```

### Task 2: 扩展后端插件任务契约

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

测试 `/api/plugin/jobs/{id}/refresh-result` 仅接受合法状态（`pending|refreshing|success|failed`），并验证失败消息可持久化且不改变任务 `status=done`。

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/test_core.py -k refresh_result -q`
Expected: FAIL。

- [ ] **Step 3: Implement validation and message persistence**

为刷新请求新增 Pydantic body 模型 `{state,message}`；无效状态返回 422；将 `refresh_state` 与消息写入任务记录，兼容旧的 query 参数调用。

- [ ] **Step 4: Run focused and full tests**

Run: `pytest tests/test_core.py -k refresh_result -q && pytest -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_core.py
git commit -m "feat: persist Emby refresh status"
```

### Task 3: 添加 Emby 媒体菜单提交动作

**Files:**
- Create: `emby-plugin/MediaMenu.cs`
- Modify: `emby-plugin/Plugin.cs`
- Modify: `emby-plugin/SubtitleCloudApi.cs`
- Modify: `emby-plugin/SubtitleCloudPlugin.csproj`

- [ ] **Step 1: Write static contract tests**

在 `tests/test_emby_plugin.py` 检查项目包含 `IItemMenu` 实现、仅接受 Movie/Episode、动作名“生成云字幕”、请求字段 `input_path/emby_item_id/display_title/av_code/poster_url`。

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_emby_plugin.py -q`
Expected: FAIL。

- [ ] **Step 3: Implement menu provider**

实现 Emby 菜单接口，注入 `IUserManager`/`IServerApplicationHost`/`HttpClient`；从 `BaseItem` 取得路径与元数据，应用 `PathMapping`，调用 `/api/plugin/jobs`，返回成功/失败通知。通过 `Plugin.GetPages` 或服务注册暴露 provider。

- [ ] **Step 4: Build plugin**

Run: `dotnet build emby-plugin/SubtitleCloudPlugin.csproj`
Expected: 编译成功。

- [ ] **Step 5: Commit**

```bash
git add emby-plugin
git commit -m "feat: add Emby video media menu action"
```

### Task 4: 实现插件任务进度页与刷新重试

**Files:**
- Modify: `emby-plugin/PluginPage.html`
- Modify: `emby-plugin/SubtitleCloudApi.cs`
- Modify: `tests/test_emby_plugin.py`

- [ ] **Step 1: Write failing static tests**

断言页面包含任务表格、`/api/plugin/jobs` 轮询、页面隐藏暂停、完成任务触发刷新、最多 3 次重试和 `refresh-result` 回写。

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_emby_plugin.py -q`
Expected: FAIL。

- [ ] **Step 3: Implement page and API methods**

在页面脚本中用 `setInterval` 轮询，渲染状态/阶段/进度/输出数量；对 `done` 且 `refresh_state=pending` 的任务调用 Emby `/Items/{id}/Refresh`，按 1s/2s/4s 重试，成功或最终失败调用后端 `refresh-result`。

- [ ] **Step 4: Build and run tests**

Run: `dotnet build emby-plugin/SubtitleCloudPlugin.csproj && pytest -q`
Expected: 编译与测试均通过。

- [ ] **Step 5: Commit**

```bash
git add emby-plugin tests/test_emby_plugin.py
git commit -m "feat: add plugin progress and metadata refresh"
```

### Task 5: 端到端验证与文档更新

**Files:**
- Modify: `emby-plugin/README.md`
- Modify: `tests/test_api_contract_static.py`

- [ ] **Step 1: Add API contract assertions**

断言插件任务接口字段、刷新状态接口和认证头保持稳定。

- [ ] **Step 2: Run complete verification**

Run: `pytest -q && dotnet build emby-plugin/SubtitleCloudPlugin.csproj`
Expected: 全部测试通过且无编译错误。

- [ ] **Step 3: Document installation/configuration**

补充菜单使用、映射示例、Emby URL/令牌配置、刷新失败状态说明。

- [ ] **Step 4: Commit**

```bash
git add emby-plugin/README.md tests/test_api_contract_static.py
git commit -m "docs: document Emby subtitle workflow"
```
