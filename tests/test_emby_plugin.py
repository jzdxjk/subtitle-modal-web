from pathlib import Path

from app.media import (
    apply_path_mappings,
    classify_strm_source,
    output_subtitle_path_for_plugin,
    resolve_emby_media_path,
)

PLUGIN = Path(__file__).resolve().parents[1] / "emby-plugin"


def test_classify_strm_source_supports_http_and_local(tmp_path):
    http = tmp_path / "ABC-123.strm"
    http.write_text("https://media.example/redirect\n", encoding="utf-8")
    local = tmp_path / "ABC-124.strm"
    local.write_text(r"\\server\share\ABC-124.mp4" + "\n", encoding="utf-8")

    assert classify_strm_source(http) == ("strm-http", "https://media.example/redirect")
    assert classify_strm_source(local) == ("strm-local", r"\\server\share\ABC-124.mp4")


def test_plugin_output_follows_media_directory_and_stem(tmp_path):
    media = tmp_path / "Movie.strm"
    assert output_subtitle_path_for_plugin(media, "srt") == tmp_path / "Movie.zh.srt"


def test_path_mappings_use_longest_case_insensitive_prefix():
    mappings = "D:/Media=/srv/media\nD:/Media/Movies=/srv/movies\ninvalid"
    assert apply_path_mappings("d:/media/movies/Film.mkv", mappings) == "/srv/movies/Film.mkv"


def test_path_mappings_keep_unmatched_paths():
    assert apply_path_mappings("E:/Other/Film.mkv", "D:/Media=/srv/media") == "E:/Other/Film.mkv"


def test_resolve_emby_media_path_finds_redirect_url_suffix_under_media_root(tmp_path):
    media = tmp_path / "影视库" / "AV" / "有码" / "SAME-237" / "SAME-237.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"media")

    resolved = resolve_emby_media_path(
        "http://172.17.0.1:8115/api/redirect115/token/object/"
        "%E5%BD%B1%E8%A7%86%E5%BA%93/AV/%E6%9C%89%E7%A0%81/SAME-237/SAME-237.mp4",
        tmp_path,
    )

    assert resolved == media


def test_plugin_injects_movie_episode_shortcut_and_submit_route():
    service = (PLUGIN / "ShortcutMenuService.cs").read_text(encoding="utf-8")
    route = (PLUGIN / "GetShortcutMenu.cs").read_text(encoding="utf-8")
    project = (PLUGIN / "SubtitleCloudPlugin.csproj").read_text(encoding="utf-8")
    assert "/SubtitleCloud/submit" in route
    assert "api/plugin/jobs" in service
    assert "emby_item_id" in service
    assert "display_title" in service
    assert 'var taskType = "native"' in service
    assert '? "strm-http"' in service
    assert "task_type = taskType" in service
    assert "PosterUrl" in service
    assert "ILibraryManager" in service
    assert "GetItemById" in service
    assert "GetMediaSources" in service
    assert "mediaSource.Path" in service
    assert "item.Path" in service
    assert "File.ReadLines" in service
    assert 'EndsWith(".strm"' in service
    assert "inputPath = strmSource" not in service
    assert "ILogManager" in service
    assert "SubtitleCloud submit" in service
    assert 'Route("/{Web}/modules/shortcuts.js"' not in route
    assert 'EmbeddedResource Include="shortcuts.js"' not in project


def test_plugin_configuration_page_has_emby_view_root():
    page = (PLUGIN / "PluginPage.html").read_text(encoding="utf-8")
    controller = (PLUGIN / "SubtitleCloudPage.js").read_text(encoding="utf-8")
    plugin = (PLUGIN / "Plugin.cs").read_text(encoding="utf-8")
    project = (PLUGIN / "SubtitleCloudPlugin.csproj").read_text(encoding="utf-8")
    assert 'Name = "subtitlecloudv2"' in plugin
    assert 'Name = "subtitlecloud.html"' not in plugin
    assert 'is="emby-scroller"' in page
    assert 'class="view flex flex-direction-column scrollFrameY flex-grow"' in page
    assert 'data-controller="__plugin/subtitlecloudjsv2"' in page
    assert 'class="scrollSlider ' in page
    assert 'data-src="/SubtitleCloud/dashboard"' in page
    assert 'EmbeddedResource Include="Dashboard.html"' in project
    assert 'EmbeddedResource Include="SubtitleCloudPage.js"' in project
    assert 'Name = "subtitlecloudjsv2"' in plugin
    assert "BaseView.apply(this, arguments)" in controller
    assert "View.prototype.onResume" in controller
    assert "View.prototype.onPause" in controller
    assert 'frame.setAttribute("src", "about:blank")' in controller
    assert "body{" not in page
    assert "#SubtitleCloudConfigurationPage" in page
    assert "subtitleCloudFrame" in page


def test_plugin_progress_page_refreshes_completed_items_with_bounded_retries():
    page = (PLUGIN / "Dashboard.html").read_text(encoding="utf-8")
    service = (PLUGIN / "ShortcutMenuService.cs").read_text(encoding="utf-8")
    assert "document.hidden" in page
    assert "/SubtitleCloud/jobs" in page
    assert 'status===\'done\').slice(0,5)' in page
    assert 'status===\'failed\').slice(0,5)' in page
    assert '"/api/plugin/jobs"' in service


def test_plugin_shortcut_uses_toast_and_preserves_existing_shortcut_script():
    service = (PLUGIN / "ShortcutMenuService.cs").read_text(encoding="utf-8")
    entrypoint = (PLUGIN / "SubtitleCloudWebEntryPoint.cs").read_text(encoding="utf-8")
    module = (PLUGIN / "SubtitleCloudPlugin.js").read_text(encoding="utf-8")
    project = (PLUGIN / "SubtitleCloudPlugin.csproj").read_text(encoding="utf-8")
    assert "StrmAssistant" not in service
    assert "ModifiedShortcutsString" not in service
    assert 'serviceUrl.Contains("127.0.0.1:8898")' not in service
    assert "statusCode < 200 || statusCode > 299" in service
    assert "字幕服务返回" in service
    assert "StrmAssistant" not in entrypoint
    assert "ModifiedShortcutsString" not in entrypoint
    assert "IServerEntryPoint" in entrypoint
    assert 'EmbeddedResource Include="SubtitleCloudPlugin.js"' in project
    assert 'EmbeddedResource Include="shortcuts.js"' not in project
    assert "云字幕任务已提交" in module
    assert "toast(message)" in module


def test_plugin_web_module_registers_one_movie_or_episode_command_source():
    module = (PLUGIN / "SubtitleCloudPlugin.js").read_text(encoding="utf-8")
    assert "__subtitleCloudCommandSourceRegistered" in module
    assert "registerCommandSource" in module
    assert "options.item && [options.item]" in module
    assert 'item.Type === "Movie" || item.Type === "Episode"' in module
    assert "items.length !== 1" in module
    assert 'id: "subtitle_cloud"' in module
    assert 'name: "生成云字幕"' in module
    assert 'ApiClient.getUrl("SubtitleCloud/submit")' in module


def test_plugin_web_loader_injection_is_bounded_idempotent_and_reversible():
    entrypoint = (PLUGIN / "SubtitleCloudWebEntryPoint.cs").read_text(encoding="utf-8")
    assert 'ModuleUrl = "./modules/SubtitleCloudPlugin.js"' in entrypoint
    assert 'Anchor = "Promise.all(list.map(loadPlugin))"' in entrypoint
    assert entrypoint.count("source.IndexOf(Injection") == 2
    assert "source.IndexOf(Anchor" in entrypoint
    assert 'appPath + ".subtitlecloud.bak"' in entrypoint
    assert 'path + ".subtitlecloud.tmp"' in entrypoint
    assert "File.Replace" in entrypoint
    assert "source.Replace(Injection, string.Empty)" in entrypoint
    assert "File.Delete(modulePath)" in entrypoint


def test_plugin_module_uses_default_export_from_emby_itemmanager():
    module = (PLUGIN / "SubtitleCloudPlugin.js").read_text(encoding="utf-8")
    assert "modules[1].default || modules[1]" in module


def test_plugin_page_has_lifecycle_cleanup_and_active_job_sections():
    page = (PLUGIN / "Dashboard.html").read_text(encoding="utf-8")
    assert "beforeunload" in page
    assert "setInterval" in page
    assert "clearInterval" in page
    assert "busy" in page
    assert "activeJobs" in page
    assert "recentDone" in page
    assert "recentFailed" in page
    assert "document.hidden" in page


def test_plugin_page_prefers_visible_route_view_over_cached_hidden_view():
    page = (PLUGIN / "PluginPage.html").read_text(encoding="utf-8")
    assert "<iframe" in page
    assert "position:" not in page


def test_plugin_page_stops_refresh_retries_after_lifecycle_cleanup():
    page = (PLUGIN / "Dashboard.html").read_text(encoding="utf-8")
    assert "beforeunload" in page
    assert "document.hidden||busy" in page
