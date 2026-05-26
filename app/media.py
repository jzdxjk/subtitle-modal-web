from __future__ import annotations

import hashlib
import re
import subprocess
import threading
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"}
# 匹配 AV 番号格式：2-5 位大写字母 + 连字符 + 3-5 位数字（含 FC2-PPV 格式）
AV_PATTERN = re.compile(r"(?:\d+)?[A-Z]{2,5}-\d{3,5}|FC2-[A-Z]{3}-\d{5,7}|FC2-\d{6,7}", re.IGNORECASE)


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def extract_av_code(path: Path) -> str | None:
    """从文件名中提取 AV 番号，如 FNS-192、EBWH-309，找不到返回 None"""
    match = AV_PATTERN.search(path.stem)
    return match.group(0) if match else None


def normalize_av_code(code: str) -> str:
    """规范化 AV 番号：去掉数字前缀、转小写。
    用于 DBO 搜索回退。
    300Mium-1336 → mium-1336
    250Idol-456  → idol-456
    FNS-192      → fns-192
    FC2-PPV-1234567 → fc2-ppv-1234567
    """
    code_lower = code.lower()
    if code_lower.startswith("fc2"):
        return code_lower
    prefix, _, number = code_lower.partition("-")
    # 去掉前缀开头的数字（如 "300mium" → "mium"）
    clean_prefix = prefix.lstrip("0123456789")
    if not clean_prefix:
        return code_lower  # fallback: 前缀全是数字就原样返回
    return f"{clean_prefix}-{number}"


def discover_media(input_path: Path) -> list[Path]:
    """发现媒体文件，只保留文件名包含 AV 番号的"""
    if input_path.is_file():
        return [input_path] if (is_video_file(input_path) or is_audio_file(input_path)) and extract_av_code(input_path) else []
    if not input_path.is_dir():
        return []
    return sorted(
        path for path in input_path.rglob("*")
        if path.is_file() and (is_video_file(path) or is_audio_file(path)) and extract_av_code(path) is not None
    )


def output_subtitle_path(media_path: Path, output_root: Path, fmt: str) -> Path:
    """输出字幕路径：/output/{番号}.{fmt}，如 /output/FNS-192.srt"""
    av_code = extract_av_code(media_path) or media_path.stem
    return output_root / f"{av_code}.{fmt}"


def cache_audio_path(media_path: Path, cache_dir: Path) -> Path:
    digest = hashlib.sha1(str(media_path).encode("utf-8")).hexdigest()[:12]
    return cache_dir / "audio" / f"{media_path.stem}-{digest}.m4a"


def build_ffmpeg_command(input_path: Path, audio_path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "aac",
        "-b:a",
        "128k",
        str(audio_path),
    ]


def _parse_ffmpeg_duration(line: str) -> float | None:
    """从 ffmpeg 的 Duration: 行解析总时长（秒）"""
    import re
    m = re.search(r'Duration: (\d+):(\d+):(\d+)\.(\d+)', line)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100
    return None


def _parse_ffmpeg_time(line: str) -> float | None:
    """从 ffmpeg 的 time= 行解析当前进度（秒）"""
    import re
    m = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 10
    return None


def prepare_audio(media_path: Path, cache_dir: Path, on_progress=None, is_cancelled_fn=None) -> Path:
    """
    提取音频。若文件已是音频格式则直接返回。
    on_progress: Callable[[int], None] | None — 进度回调（0-100）
    is_cancelled_fn: Callable[[], bool] | None — 取消检查，返回 True 时杀 ffmpeg
    """
    if is_audio_file(media_path):
        return media_path
    audio_path = cache_audio_path(media_path, cache_dir)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_path.exists() and audio_path.stat().st_size > 0:
        return audio_path
    command = build_ffmpeg_command(media_path, audio_path)
    proc = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)

    total_duration: float | None = None
    last_report = -1

    def _reader() -> None:
        nonlocal total_duration, last_report
        for line in proc.stderr:
            if is_cancelled_fn and is_cancelled_fn():
                proc.kill()
                return
            if total_duration is None:
                d = _parse_ffmpeg_duration(line)
                if d is not None and d > 0:
                    total_duration = d
            t = _parse_ffmpeg_time(line)
            if t is not None and total_duration and total_duration > 0:
                pct = min(int(t / total_duration * 100), 99)
                if pct > last_report:
                    last_report = pct
                    if on_progress:
                        on_progress(pct)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    proc.wait()
    thread.join(timeout=2)

    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ''
        raise RuntimeError(f"ffmpeg failed: {stderr[-2000:]}")
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("ffmpeg finished but audio file was not created")
    return audio_path