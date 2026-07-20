from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "app" / "static" / "index.html"
APP_JS = ROOT / "app" / "static" / "app.js"
STYLES = ROOT / "app" / "static" / "styles.css"


def test_queue_ui_contains_neumorphic_shell_and_interactions():
    index = INDEX.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert 'id="queue-density"' not in index
    assert 'data-density="compact"' not in index
    assert 'queue-surface' in index
    assert 'queue-summary' not in index
    assert 'queue-toolbar' not in index
    assert 'id="queue-search"' not in index
    assert ".job-row" in styles
    assert ".job-status-line" in styles
    assert ".job-time-block" in styles
    assert ".job-progress-line" in styles
    assert "densityMode" not in app_js
    assert "renderJobRow" in app_js


def test_desktop_queue_tabs_do_not_inherit_button_dividers_or_shadows():
    styles = STYLES.read_text(encoding="utf-8")

    assert ".queue-tabs-bar .tab-btn,\n.queue-tabs-bar .tab-btn:hover,\n.queue-tabs-bar .tab-btn:active" in styles
    assert ":root.dark .queue-tabs-bar .tab-btn,\n:root.dark .queue-tabs-bar .tab-btn:hover,\n:root.dark .queue-tabs-bar .tab-btn:active" in styles


def test_queue_rows_keep_delete_action_for_existing_jobs():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "deleteJob(jobId)" in app_js
    assert 'actions.push(`<button class="delete-btn job-action" data-id="${job.id}" title="删除">' in app_js
    assert "删除" in app_js
    assert 'querySelectorAll(".delete-btn[data-id]")' in app_js


def test_queue_rows_hide_delete_action_until_active_jobs_finish():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "if (!isRunning && !isQueued && !isCancelling && !isDone) {" in app_js
    assert "active job must be cancelled before deletion" in (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_completed_rows_replace_status_and_actions_with_completion_details():
    app_js = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert 'else if (isDone)' not in app_js
    assert 'class="view-btn job-action"' not in app_js
    assert "!isCancelling && !isDone" in app_js
    assert 'class="job-completed-total"' in app_js
    assert 'class="job-completed-phases"' in app_js
    assert 'class="job-completed-at"' in app_js
    assert 'completedAtText' in app_js
    assert ".queue-list-head.completed" in styles
    assert ".job-row.done .job-row-center" not in styles


def test_completed_tab_uses_semantic_headers_without_status_or_actions():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert '["番号", "总耗时", "本地 / 云端", "完成时间"]' in app_js
    assert "listHead.classList.toggle(\"completed\", tab === \"completed\")" in app_js


def test_waiting_local_hides_progress_and_keeps_all_timers_unstarted():
    app_js = APP_JS.read_text(encoding="utf-8")
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    waiting_block = worker.split('phase="waiting_local"', 1)[1].split("async with local_lock", 1)[0]

    assert 'job.phase !== "waiting_local"' in app_js
    assert 'phase === "waiting_local"' in app_js
    assert 'progress=0,' in waiting_block
    assert 'progress=max(1, (index - 1) * 35 // total_media)' not in waiting_block


def test_desktop_and_mobile_queue_layouts_have_separate_alignment_rules():
    styles = STYLES.read_text(encoding="utf-8")
    desktop = styles.split("@media (max-width: 900px)", 1)[0]
    mobile = styles.split("@media (max-width: 900px)", 1)[1]

    assert ".job-row:not(.done) .job-row-center" in desktop
    assert "align-items: center;" in desktop.split(".job-row:not(.done) .job-row-center", 1)[1].split("}", 1)[0]
    assert ".job-row.done .job-row-main" in desktop
    assert '"identity completed"' in mobile
    assert '"total phases"' in mobile


def test_desktop_status_detail_rule_closes_before_time_block_rules():
    styles = STYLES.read_text(encoding="utf-8")

    assert ".job-row:not(.done) .job-status-detail {\n  width: 100%;\n  text-align: left;\n}" in styles
    assert ".job-time-block {\n  display: flex;\n  flex-direction: column;" in styles


def test_running_jobs_sort_started_tasks_first_in_start_order():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "const aStarted = Number(a.started_at || 0);" in app_js
    assert "const bStarted = Number(b.started_at || 0);" in app_js
    assert "if (Boolean(aStarted) !== Boolean(bStarted)) return aStarted ? -1 : 1;" in app_js
    assert "return (a.created_at || 0) - (b.created_at || 0);" in app_js


def test_waiting_jobs_do_not_start_timers_and_redraws_keep_live_values():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "function livePhaseSeconds(job, kind)" in app_js
    assert "const startedAt = Number(job.started_at || 0);" in app_js
    assert "job.started_at || job.created_at" not in app_js
    assert 'const localSeconds = livePhaseSeconds(job, "local");' in app_js
    assert 'const cloudSeconds = livePhaseSeconds(job, "cloud");' in app_js


def test_mobile_pager_is_one_compact_aligned_control():
    styles = STYLES.read_text(encoding="utf-8")

    assert ".pager-shell {" in styles
    assert "grid-auto-columns: 36px;" in styles
    assert ".pager-shell button {" in styles
    assert "width: 36px;" in styles
    assert "height: 36px;" in styles


def test_queue_rows_use_av_code_and_live_backend_phase_timings():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert 'const avCode = extractAvCode(job.input_path || "")' in app_js
    assert 'const shortId = avCode || `#${String(job.id).slice(0, 8).toUpperCase()}`' in app_js
    assert "job.phase" in app_js
    assert "job.local_seconds" in app_js
    assert "job.cloud_seconds" in app_js
    assert 'data-timer-kind="local"' in app_js
    assert 'data-timer-kind="cloud"' in app_js
    assert "durationSeconds * 0.22" not in app_js


def test_mobile_queue_rows_are_stacked_and_progress_spans_the_card():
    styles = STYLES.read_text(encoding="utf-8")

    mobile = styles.split("@media (max-width: 900px)", 1)[1].split("@media (max-width: 520px)", 1)[0]
    assert 'grid-template-areas:\n      "identity actions"\n      "status status"\n      "timing timing";' in mobile
    assert ".job-progress-line {\n    width: 100%;" in mobile
    assert ".queue-list-head {\n    display: none;" in mobile


def test_phone_gallery_sizes_cards_to_two_per_viewport():
    styles = STYLES.read_text(encoding="utf-8")
    phone = styles.split("@media (max-width: 520px)", 1)[1]

    assert "flex-basis: calc((100vw - 56px) / 2);" in phone


def test_frontend_visible_text_is_not_mojibake():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (INDEX, APP_JS)
    )

    for mojibake in ("�", "瀛楀", "鎺掗", "杩愯", "澶辫", "宸插", "鍙栨", "鉁", "鈥", "鑾峰"):
        assert mojibake not in combined
