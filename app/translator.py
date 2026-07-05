from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path

logger = logging.getLogger("subtitle.translator")

# SRT 时间轴行正则
_SRT_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}$")


def _parse_srt(srt_path: Path) -> list[dict]:
    """解析 SRT 文件，返回 [{index, timestamp, text}] 列表"""
    blocks: list[dict] = []
    if not srt_path.exists():
        return blocks
    content = srt_path.read_text(encoding="utf-8")
    # 按双换行切块
    raw_blocks = re.split(r"\n\s*\n", content.strip())
    for block in raw_blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        # 跳过空行
        lines = [l.strip() for l in lines if l.strip()]
        if len(lines) < 2:
            continue
        idx_line = lines[0]
        time_line = lines[1]
        text_lines = lines[2:]
        if not _SRT_TIME_RE.match(time_line):
            continue
        try:
            index = int(idx_line)
        except ValueError:
            continue
        blocks.append({
            "index": index,
            "timestamp": time_line,
            "text": "\n".join(text_lines),
        })
    return blocks


def _build_srt(blocks: list[dict]) -> str:
    """将 blocks 重建为 SRT 文本"""
    parts: list[str] = []
    for i, block in enumerate(blocks, start=1):
        parts.append(str(i))
        parts.append(block["timestamp"])
        parts.append(block["text"])
        parts.append("")
    return "\n".join(parts) + "\n"


def translate_srt(
    ja_srt_path: Path,
    zh_srt_path: Path,
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    batch_size: int = 20,
) -> None:
    """
    将日文 SRT 翻译为中文 SRT。

    Args:
        ja_srt_path: 日文 SRT 文件路径
        zh_srt_path: 输出中文 SRT 文件路径
        api_url: OpenAI 兼容 API 的 base URL
        api_key: API Key
        model: 模型名称
        system_prompt: 自定义翻译 system prompt
        batch_size: 每次翻译的条目数
    """
    blocks = _parse_srt(ja_srt_path)
    if not blocks:
        logger.warning("translator: empty SRT, skipping: %s", ja_srt_path)
        zh_srt_path.write_text("", encoding="utf-8")
        return

    url = api_url.rstrip("/") + "/chat/completions"

    translated_blocks: list[dict] = []
    total = len(blocks)

    for start in range(0, total, batch_size):
        batch = blocks[start : start + batch_size]
        # 构建翻译请求：用分隔符标记每条
        lines = [b["text"] for b in batch]
        separator = "\n---\n"
        input_text = separator.join(lines)

        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请将以下日文字幕逐条翻译为中文，用 \"---\" 分隔每条结果，只返回翻译内容不要添加任何说明：\n\n{input_text}"},
            ],
            "temperature": 0.3,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

        try:
            r = urllib.request.urlopen(req, timeout=120)
            resp = json.loads(r.read())
            result_text = resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error("translator: API call failed for batch %d-%d: %s", start + 1, start + len(batch), e)
            # 失败时保留原文
            for b in batch:
                translated_blocks.append({"index": b["index"], "timestamp": b["timestamp"], "text": b["text"]})
            continue

        # 按分隔符拆分
        translated_lines = result_text.split("---")
        translated_lines = [t.strip() for t in translated_lines]

        # 匹配回原始条目
        for i, b in enumerate(batch):
            text = translated_lines[i] if i < len(translated_lines) else b["text"]
            # 清理可能的编号前缀（如 "1. 你好" → "你好"）
            text = re.sub(r"^\d+[\.\、\)]\s*", "", text).strip()
            if not text:
                text = b["text"]
            translated_blocks.append({"index": b["index"], "timestamp": b["timestamp"], "text": text})

        logger.info("translator: batch %d-%d/%d done", start + 1, start + len(batch), total)

    zh_srt_path.parent.mkdir(parents=True, exist_ok=True)
    zh_srt_path.write_text(_build_srt(translated_blocks), encoding="utf-8")
    logger.info("translator: wrote %d blocks to %s", len(translated_blocks), zh_srt_path)
