import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "app" / "static" / "index.html"
APP_JS = ROOT / "app" / "static" / "app.js"
STYLES = ROOT / "app" / "static" / "styles.css"
MANIFEST = ROOT / "app" / "static" / "manifest.json"
ICON_192 = ROOT / "app" / "static" / "icons" / "icon-192.svg"
ICON_512 = ROOT / "app" / "static" / "icons" / "icon-512.svg"


def test_frontend_uses_new_neumorphic_shell():
    html = INDEX.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")

    assert "Subtitle Cloud" in html
    assert "字幕画廊" in html
    assert '<h2 id="topbar-heading"><span class="topbar-title-text">Subtitle Cloud</span><small>v3.01</small></h2>' in html
    assert "topbar" in html
    assert "gallery-summary" not in html
    assert "summary-stats" not in html
    assert "home-count" not in html
    assert "running-count" not in html
    assert "failed-count" not in html
    assert ".summary-stats" not in css
    assert ".queue-density" not in css
    assert ".neu-convex" in css
    assert ".neu-concave" in css
    assert "--surface: #fcf8f8" in css
    assert "--shadow-dark: #AEAEC0" in css


def test_brand_title_places_chinese_name_under_subtitle_and_version_under_cloud():
    html = INDEX.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert '<h1 class="brand-title">' in html
    assert '<span class="brand-word"><span>Subtitle</span><small>字幕云</small></span>' in html
    assert '<span class="brand-word"><span>Cloud</span><small id="version">v3.01</small></span>' in html
    assert "字幕云 AI" not in html
    assert "brand-meta" not in html
    assert ".brand-title {\n  display: grid;" in css
    assert "grid-template-columns: repeat(2, max-content);" in css
    assert ".brand-word small" in css
    assert 'v.textContent = r.version || "v3.01"' in app_js


def test_pwa_icons_use_sync_cloud_symbol():
    manifest = MANIFEST.read_text(encoding="utf-8")
    icon_192 = ICON_192.read_text(encoding="utf-8")
    icon_512 = ICON_512.read_text(encoding="utf-8")

    assert "/static/icons/icon-reference-192.png" in manifest
    assert "/static/icons/icon-reference-512.png" in manifest
    assert (ROOT / "app" / "static" / "icons" / "icon-reference-192.png").is_file()
    assert (ROOT / "app" / "static" / "icons" / "icon-reference-512.png").is_file()
    for icon in (icon_192, icon_512):
        assert 'fill="#020305"' in icon
        assert 'stroke="#2b313b"' in icon
        assert 'class="sync-arrow"' in icon
        assert 'class="cloud"' in icon
        assert "瀛?" not in icon


def test_frontend_keeps_required_views_and_navigation():
    html = INDEX.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    for view in ("home", "queue", "submit", "config", "transcribe"):
        assert f'id="view-{view}"' in html
        assert f'data-view="{view}"' in html
    assert 'id="dock-mobile"' in html
    assert 'id="theme-toggle"' in html
    assert 'id="theme-toggle-mobile"' in html
    assert 'document.querySelectorAll(".dock-item[data-view], .dock-mobile-item[data-view]")' in app_js
    assert 'switchView(btn.dataset.view)' in app_js
    assert 'if (headingTitle) headingTitle.textContent = "Subtitle Cloud";' in app_js
    assert "VIEW_TITLES[viewId]" not in app_js
    assert 'class="config-new-task"' not in html
    assert 'body[data-view="config"]' not in STYLES.read_text(encoding="utf-8")


def test_frontend_persists_theme_and_active_view_across_refreshes():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert 'localStorage.removeItem("subtitle-theme")' not in app_js
    assert 'const savedTheme = localStorage.getItem("subtitle-theme") || "light";' in app_js
    assert 'setTheme(savedTheme);' in app_js
    assert 'localStorage.setItem("subtitle-active-view", viewId);' in app_js
    assert 'const initialView = localStorage.getItem("subtitle-active-view") || "home";' in app_js
    assert 'switchView(initialView);' in app_js


def test_mobile_buttons_and_gallery_do_not_snap_or_show_square_focus():
    css = STYLES.read_text(encoding="utf-8")

    assert "scroll-snap-type" not in css
    assert "scroll-snap-align" not in css
    assert ".dock-mobile-item:focus,\n  .dock-mobile-item:focus-visible" in css
    assert "outline: none;" in css
    assert "-webkit-tap-highlight-color: transparent;" in css


def test_mobile_task_rows_can_wrap_without_overlap():
    css = STYLES.read_text(encoding="utf-8")
    mobile_css = css.split("@media (max-width: 900px)", 1)[1]

    assert "min-height: auto;" in mobile_css
    assert 'grid-template-areas:\n      "identity actions"\n      "status status"\n      "timing timing";' in mobile_css
    assert "max-height: 118px;" in mobile_css
    assert "overflow: auto;" in mobile_css
    assert "min-width: 0;" in mobile_css


def test_mobile_topbar_title_keeps_version_badge():
    html = INDEX.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert '<h2 id="topbar-heading"><span class="topbar-title-text">Subtitle Cloud</span><small>v3.01</small></h2>' in html
    assert ".topbar h2 {\n  display: inline-flex;" in css
    assert "align-items: center;" in css.split(".topbar h2 {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: nowrap;" in css
    assert "gap: 5px;" in css.split(".topbar h2 {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap;" in css
    assert ".topbar h2 small {\n  position: static;" in css
    assert "flex-shrink: 0;" in css
    assert "transform: none;" in css.split(".topbar h2 small {", 1)[1].split("}", 1)[0]
    assert 'const headingTitle = heading ? heading.querySelector(".topbar-title-text") : null;' in app_js
    assert "heading.textContent = \"Subtitle Cloud\"" not in app_js


def test_view_headers_show_consistent_english_and_chinese_titles():
    html = INDEX.read_text(encoding="utf-8")

    expected_titles = {
        "view-home": "字幕画廊",
        "view-queue": "任务队列",
        "view-submit": "提交任务",
        "view-config": "配置",
        "view-transcribe": "转录设置",
    }
    for view_id, chinese in expected_titles.items():
        marker = f'id="{view_id}"'
        assert marker in html
        view_html = html.split(marker, 1)[1].split('<section class="view"', 1)[0]
        assert f"<h1>{chinese}</h1>" in view_html

    for english in ("Subtitle Gallery", "Task Queue", "Submit Task", "Configuration Center", "Transcribe"):
        assert f'<p class="eyebrow">{english}</p>' not in html
    assert "集中查看已完成的字幕任务，按日期打包下载生成结果。" not in html
    assert "集中处理转录、翻译与字幕导出任务，实时查看云端 GPU 进度。" not in html


def test_config_page_has_functional_controls_for_existing_api_fields():
    html = INDEX.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert '<select name="default_gpu"' in html
    for gpu in ("T4", "L4", "A10", "L40S", "A100", "A100-40GB", "A100-80GB", "RTX-PRO-6000", "H100", "H100!", "H200", "B200", "B200+", "B300"):
        assert f'value="{gpu}"' in html
    assert '<select name="repo_branch"' in html
    for version in ("v1.10", "v1.9", "v1.8", "v1.7", "v1.6", "v1.5", "v1.4", "v1.3", "v1.2", "v1.1", "v1.0"):
        assert f'value="{version}"' in html
    assert '<input type="hidden" name="default_model" value="chickenrice"' in html
    assert 'name="dbo_api_url"' in html
    assert 'name="dbo_api_key"' in html
    assert 'id="test-dbo-btn"' in html
    assert 'name="default_move_target_dir"' not in html
    assert 'name="enable_watchdog" type="checkbox"' in html
    assert 'name="watchdog_interval_seconds" type="range"' in html
    assert 'name="max_workers" type="range"' in html
    assert 'name="default_timeout_seconds" type="range"' in html
    assert 'name="min_file_size_mb" type="range"' in html
    assert ".range-proxy" in css
    assert "syncRangeControl" in app_js
    assert "initRangeControls" in app_js


def test_config_page_stacks_controls_on_phone_viewports():
    css = STYLES.read_text(encoding="utf-8")
    mobile_shell_css = css.split("@media (max-width: 900px)", 1)[1].split("@media (max-width: 520px)", 1)[0]

    assert "@media (max-width: 520px)" in css
    assert ".config-tuning-grid {\n    grid-template-columns: 1fr;" in mobile_shell_css
    assert ".tuning-wide {\n    grid-column: auto;" in mobile_shell_css
    assert ".config-grid {\n    grid-template-columns: 1fr;" in css
    assert ".config-fields-two {\n    grid-template-columns: 1fr;" in css
    assert ".config-tuning-grid {\n    grid-template-columns: 1fr;" in css
    assert ".tuning-wide {\n    grid-column: auto;" in css


def test_config_canvas_uses_full_view_width_like_other_pages():
    css = STYLES.read_text(encoding="utf-8")

    assert ".config-canvas {\n  width: 100%;" in css
    assert "width: min(100%, 1120px)" not in css
    assert "margin-inline: auto" not in css


def test_queue_surface_reuses_the_config_panel_concave_frame():
    html = INDEX.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")

    assert 'class="queue-surface neu-concave"' in html
    assert 'id="job-form" class="card neu-concave"' in html
    assert 'id="transcribe-form" class="card neu-concave"' in html
    assert 'page-surface' not in html
    assert ".neu-concave {\n  background: var(--surface);\n  border: 1px solid var(--outline-variant);\n  border-radius: var(--radius-lg);\n  box-shadow: inset 5px 5px 10px var(--shadow-pressed-dark), inset -5px -5px 10px var(--shadow-pressed-light);" in css
    assert ":root.dark .config-panel,\n:root.dark .card.neu-concave,\n:root.dark .queue-surface.neu-concave" in css


def test_mobile_ui_uses_phone_first_app_shell():
    css = STYLES.read_text(encoding="utf-8")

    assert "@media (max-width: 900px)" in css
    assert ".topbar {\n    display: flex;" in css
    assert "padding: 74px 14px 104px;" in css
    assert "left: 50%;" in css
    assert "width: min(calc(100vw - 48px), 560px);" in css
    assert "border-radius: 999px;" in css
    assert "backdrop-filter: blur(22px) saturate(170%);" in css
    assert "transform: translateX(-50%);" in css
    assert ".queue-list-head {\n    display: none;" in css
    assert 'grid-template-areas:\n      "identity actions"\n      "status status"\n      "timing timing";' in css
    assert ".config-panel,\n  .card" in css
    assert "queue-summary-card" not in css


def test_mobile_dock_keeps_integrated_frosted_dark_mode():
    css = STYLES.read_text(encoding="utf-8")

    assert "@media (max-width: 900px)" in css
    assert ":root.dark .dock-mobile {\n    border-color: rgba(236, 244, 255, .12);" in css
    assert ":root.dark body {\n    background: linear-gradient(180deg, #020513 0%, #050817 48%, #03050d 100%);" in css
    assert ":root.dark .topbar {\n    background: rgba(5, 8, 18, .72);" in css
    assert ":root.dark .dock-mobile-item,\n  :root.dark .dock-mobile-item:hover,\n  :root.dark .dock-mobile-item:active" in css
    assert ":root.dark .dock-mobile-item.active" in css
    assert "box-shadow: none;\n    transform: none;" in css


def test_mobile_queue_tabs_are_integrated_frosted_segments():
    css = STYLES.read_text(encoding="utf-8")

    assert ".tabs::-webkit-scrollbar {\n    display: none;" in css
    assert "scrollbar-width: none;" in css
    assert ".tab-btn {\n    min-height: 38px;" in css
    assert "background: transparent;\n    box-shadow: none;" in css
    assert ":root.dark .tab-btn,\n  :root.dark .tab-btn:hover,\n  :root.dark .tab-btn:active" in css


def test_mobile_job_rows_use_desktop_inspired_compact_rows():
    css = STYLES.read_text(encoding="utf-8")

    assert ".queue-list-head {\n    display: none;" in css
    assert 'grid-template-areas:\n      "identity actions"\n      "status status"\n      "timing timing";' in css
    assert ".jobs {\n    justify-items: stretch;" in css
    assert "width: 100%;" in css
    assert "justify-self: stretch;" in css
    assert ".job-row .job-actions {\n    grid-area: actions;" in css
    assert ".job-action {\n    width: 40px;" in css
    assert ":root.dark .job.job-row {\n    border-color: rgba(236, 244, 255, .16);" in css


def test_frontend_uses_real_empty_states_not_demo_jobs():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "DEMO_JOBS" not in app_js
    assert "getQueueSourceJobs" not in app_js
    assert "demo-action" not in app_js


def test_gallery_paginates_completed_dates_in_sets_of_five():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "const daysPerPage = 5;" in app_js
    assert "const daysPerPage = 10;" not in app_js


def test_gallery_cards_offer_single_subtitle_downloads():
    app_js = APP_JS.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")

    assert "function downloadGalleryFile(jobId, fileIndex)" in app_js
    assert '"/api/jobs/" + encodeURIComponent(jobId) + "/download?file_index=" + fileIndex' in app_js
    assert 'class="gallery-download"' in app_js
    assert ".gallery-download" in css


def test_frontend_exposes_modal_account_switcher_and_monthly_cost_action():
    html = INDEX.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert 'id="modal-account-select"' in html
    assert 'id="modal-account-name"' in html
    assert 'id="topbar-avatar"' in html
    assert 'id="modal-monthly-cost"' in html
    assert '"/api/modal-accounts"' in app_js
    assert '"/api/modal-cost/month"' in app_js


def test_modal_account_actions_surface_backend_errors_as_toasts():
    app_js = APP_JS.read_text(encoding="utf-8")
    switch_handler = app_js.split('$("#modal-account-select")?.addEventListener("change"', 1)[1].split('$("#modal-account-new")', 1)[0]
    save_handler = app_js.split('$("#modal-account-save")?.addEventListener("click"', 1)[1].split('$("#modal-account-delete")', 1)[0]
    delete_handler = app_js.split('$("#modal-account-delete")?.addEventListener("click"', 1)[1].split('$("#modal-monthly-cost")', 1)[0]

    for handler in (switch_handler, save_handler, delete_handler):
        assert "try {" in handler
        assert "catch (error)" in handler
        assert "showToast(error.message, false);" in handler


def test_topbar_does_not_keep_unused_status_buttons():
    html = INDEX.read_text(encoding="utf-8")

    assert 'title="运行状态"' not in html
    assert 'title="云端连接"' not in html


def test_static_assets_are_versioned_with_the_current_service_worker_cache():
    html = INDEX.read_text(encoding="utf-8")
    service_worker = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")

    assert 'styles.css?v=117' in html
    assert 'app.js?v=117' in html
    assert 'const CACHE = "subtitle-web-v42";' in service_worker


def test_frontend_declares_a_pwa_favicon_and_password_autocomplete_hints():
    html = INDEX.read_text(encoding="utf-8")

    assert '<link rel="manifest" href="/static/manifest.json?v=42"' in html
    assert '<link rel="icon" href="/static/icons/icon-reference-192.png"' in html
    assert '<link rel="apple-touch-icon" href="/static/icons/icon-reference-192.png"' in html
    assert 'class="splash-icon" src="/static/icons/icon-reference-192.png"' in html
    assert html.count('autocomplete="current-password"') >= 4


def test_pwa_icons_use_safe_padding_and_split_maskable_purpose():
    manifest_text = (ROOT / "app" / "static" / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    service_worker = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")

    assert manifest["name"] == "字幕云翻译"
    assert manifest["short_name"] == "字幕云"
    assert "icon-reference-192.png" in manifest_text
    assert "icon-reference-512.png" in manifest_text
    assert "icon-reference-maskable-512.png" not in manifest_text
    assert '"purpose": "any"' in manifest_text
    assert '"purpose": "maskable"' not in manifest_text
    assert "icon-reference-192.png" in service_worker
    assert "icon-reference-512.png" in service_worker
    assert "icon-reference-maskable-512.png" not in service_worker


def test_transcribe_page_does_not_render_unused_status_placeholder():
    html = INDEX.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert 'id="transcribe-status"' not in html
    assert "transcribe-status" not in app_js
