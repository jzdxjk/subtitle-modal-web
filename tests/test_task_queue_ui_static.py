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


def test_config_has_five_node_metadata_selector_dialog():
    index = INDEX.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "JavDB API 配置" in index
    assert 'id="metadata-node-dialog"' in index
    assert 'id="choose-metadata-node"' in index
    assert 'name="metadata_provider"' in index
    assert 'name="javdb_api_url"' in index
    assert 'name="dbo_api_url"' in index
    assert 'name="dbo_api_key"' in index
    assert "renderMetadataNodes" in app_js
    assert 'api("/api/metadata-nodes")' in app_js
    assert "/api/metadata-nodes/probe" in app_js
    assert "/api/metadata-nodes/select" in app_js
    assert ".metadata-node-dialog" in styles
    assert ".metadata-node-row" in styles
    assert '"ip ip latency"' in styles


def test_static_shell_displays_v304_consistently():
    index = INDEX.read_text(encoding="utf-8")

    assert "v3.04" in index
    assert "v3.01" not in index


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

    assert '["番号", "大小", "总耗时", "本地 / 云端", "完成时间"]' in app_js
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


def test_desktop_running_row_time_block_is_centered_under_time_header():
    styles = STYLES.read_text(encoding="utf-8")
    desktop = styles.split("@media (max-width: 900px)", 1)[0]
    time_block = desktop.split(".job-time-block {", 1)[1].split("}", 1)[0]

    assert "justify-self: center;" in time_block


def test_queue_desktop_uses_quarter_point_columns_and_renders_size_for_all_rows():
    styles = STYLES.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "--queue-grid-columns: 12.5% 25% 25% 25% 12.5%;" in styles
    assert "--queue-completed-columns: 12.5% 25% 25% 25% 12.5%;" in styles
    assert 'class="job-size"' in app_js
    assert '"大小"' in app_js
    assert "input_size_bytes" in app_js


def test_queue_quarter_point_tracks_clear_legacy_grid_gaps():
    styles = STYLES.read_text(encoding="utf-8")
    desktop = styles.split("@media (max-width: 900px)", 1)[0]
    head = desktop.rsplit(".queue-list-head {", 1)[1].split("}", 1)[0]
    rows = desktop.rsplit("\n.job-row-main {", 1)[1].split("}", 1)[0]

    assert "gap: 0;" in head
    assert "gap: 0;" in rows


def test_queue_mobile_places_size_on_status_row_and_keeps_timing_group():
    styles = STYLES.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    mobile = styles.split("@media (max-width: 900px)", 1)[1]

    assert '"status status"' in mobile
    assert 'class="job-status-meta"' in app_js
    assert 'class="job-size-mobile"' in app_js
    assert ".job-status-meta" in mobile
    assert ".job-size-mobile" in mobile
    assert ".job-time-block" in mobile


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


def test_phone_pager_scrolls_inside_its_own_track_instead_of_overflowing_page():
    styles = STYLES.read_text(encoding="utf-8")
    phone = styles.split("@media (max-width: 520px)", 1)[1]
    pager = phone.split(".pager-shell {", 1)[1].split("}", 1)[0]

    assert "max-width: 100%;" in pager
    assert "overflow-x: auto;" in pager
    assert "justify-content: start;" in pager
    assert ".pager-shell::-webkit-scrollbar" in phone


def test_queue_pager_uses_ellipsis_instead_of_question_marks():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert 'class="pager-ellipsis">?</span>' not in app_js
    assert 'class="pager-ellipsis">&hellip;</span>' in app_js


def test_queue_pager_expands_small_page_counts_before_collapsing():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "if (totalPages <= 7)" in app_js
    assert "for (let i = 1; i <= totalPages; i++)" in app_js


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


def test_phone_gallery_gives_av_full_width_and_uses_compact_download_pill():
    styles = STYLES.read_text(encoding="utf-8")
    phone = styles.split("@media (max-width: 520px)", 1)[1]

    assert "grid-template-columns: minmax(0, 1fr) auto;" in phone
    assert "grid-column: 1 / -1;" in phone
    assert "-webkit-line-clamp: 1;" in phone
    assert "min-height: 0;" in phone
    assert "width: 44px;" in phone
    assert "height: 28px;" in phone
    assert "border-radius: 999px;" in phone
    assert "box-shadow: inset 3px 3px 6px" in phone


def test_gallery_places_format_badge_before_download_action():
    app_js = APP_JS.read_text(encoding="utf-8")
    actions = app_js.split('<div class="gallery-actions">', 1)[1].split("</div>", 1)[0]

    assert actions.index("fmt-badge") < actions.index("gallery-download")


def test_mobile_completed_size_is_right_aligned_instead_of_centered_row():
    styles = STYLES.read_text(encoding="utf-8")
    mobile = styles.split("@media (max-width: 900px)", 1)[1]
    completed = mobile.split(".job-row.done .job-size", 1)[1].split("}", 1)[0]

    assert "justify-self: end;" in completed


def test_frontend_visible_text_is_not_mojibake():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (INDEX, APP_JS)
    )

    for mojibake in ("�", "瀛楀", "鎺掗", "杩愯", "澶辫", "宸插", "鍙栨", "鉁", "鈥", "鑾峰"):
        assert mojibake not in combined
