from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class AppConfig:
    modal_token_id: str = ""
    modal_token_secret: str = ""
    hf_token: str = ""
    default_gpu: str = "T4"
    default_model: str = "chickenrice"
    default_output_dir: str = "/output"
    default_cache_dir: str = "/cache"
    default_formats: str = "srt"
    min_file_size_mb: int = 100
    default_timeout_seconds: int = 7200
    default_move_target_dir: str = ""
    enable_watchdog: bool = False
    watchdog_interval_seconds: int = 60
    max_workers: int = 1
    repo_url: str = "https://github.com/TransWithAI/Faster-Whisper-TransWithAI-ChickenRice.git"
    repo_branch: str = "v1.7"
    dbo_api_url: str = ""
    dbo_api_key: str = ""

    def merged_with_env(self) -> "AppConfig":
        data = asdict(self)
        env_map = {
            "MODAL_TOKEN_ID": "modal_token_id",
            "MODAL_TOKEN_SECRET": "modal_token_secret",
            "HF_TOKEN": "hf_token",
            "DEFAULT_GPU": "default_gpu",
            "DEFAULT_MODEL": "default_model",
            "DEFAULT_OUTPUT_DIR": "default_output_dir",
            "DEFAULT_CACHE_DIR": "default_cache_dir",
            "DEFAULT_FORMATS": "default_formats",
            "MIN_FILE_SIZE_MB": "min_file_size_mb",
            "DEFAULT_TIMEOUT_SECONDS": "default_timeout_seconds",
            "DEFAULT_MOVE_TARGET_DIR": "default_move_target_dir",
            "ENABLE_WATCHDOG": "enable_watchdog",
            "WATCHDOG_INTERVAL_SECONDS": "watchdog_interval_seconds",
            "MAX_WORKERS": "max_workers",
            "REPO_URL": "repo_url",
            "REPO_BRANCH": "repo_branch",
        }
        for env_name, field_name in env_map.items():
            value = os.getenv(env_name)
            if not value:
                continue
            if field_name in ("min_file_size_mb", "default_timeout_seconds", "watchdog_interval_seconds", "max_workers"):
                data[field_name] = int(value)
            elif field_name == "enable_watchdog":
                data[field_name] = value.lower() in ("1", "true", "yes")
            else:
                data[field_name] = value
        return AppConfig(**data)

    def redacted(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("modal_token_id", "modal_token_secret", "hf_token"):
            data[key] = redact_secret(data.get(key, ""))
        data["has_modal_token"] = bool(self.modal_token_id and self.modal_token_secret)
        data["has_hf_token"] = bool(self.hf_token)
        return data


def redact_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig().merged_with_env()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        allowed = {field.name for field in AppConfig.__dataclass_fields__.values()}
        clean = {key: value for key, value in raw.items() if key in allowed}
        return AppConfig(**clean).merged_with_env()

    def save(self, payload: dict[str, Any]) -> AppConfig:
        current = asdict(self.load())
        for key in ("modal_token_id", "modal_token_secret", "hf_token"):
            if key in payload and (not payload[key] or "***" in str(payload[key])):
                payload.pop(key)
        current.update({key: value for key, value in payload.items() if key in current})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return AppConfig(**current).merged_with_env()
