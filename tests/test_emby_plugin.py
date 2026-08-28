from pathlib import Path

from app.media import classify_strm_source, output_subtitle_path_for_plugin, apply_path_mappings


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
