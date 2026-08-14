"""Versioned non-secret runtime configuration loaded from JSON-compatible YAML."""

import json
import os
from pathlib import Path

from pydantic import Field, field_validator

from evoweave.domain.base import DomainModel


class EvoWeaveConfig(DomainModel):
    runtime_directory: str = Field(default=".runtime", min_length=1, max_length=255)
    default_provider: str = Field(default="qianwen", pattern=r"^[a-z0-9_-]+$")
    default_model_id: str = Field(default="qwen3.7-plus", min_length=1, max_length=255)
    qianwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        min_length=8,
        max_length=2_048,
    )
    sandbox_image: str = Field(default="evoweave-python:3.12", min_length=1, max_length=512)
    max_worker_steps: int = Field(default=32, ge=1, le=1_000)
    max_worker_tool_calls: int = Field(default=32, ge=1, le=1_000)
    max_worker_seconds: int = Field(default=900, ge=1, le=86_400)
    max_dynamic_tasks: int = Field(default=8, ge=1, le=128)
    split_directory_lines: int = Field(default=400, ge=1, le=1_000_000)

    @field_validator("runtime_directory")
    @classmethod
    def validate_runtime_directory(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("runtime_directory 必须是仓库内相对路径")
        return value

    @field_validator("qianwen_base_url")
    @classmethod
    def validate_qianwen_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("千问 Base URL 必须使用 HTTPS")
        return normalized


def load_config(path: Path | str | None = None) -> EvoWeaveConfig:
    if path is None:
        return EvoWeaveConfig(
            qianwen_base_url=os.environ.get(
                "EVOWEAVE_QIANWEN_BASE_URL",
                EvoWeaveConfig.model_fields["qianwen_base_url"].default,
            )
        )
    config_path = Path(path).resolve(strict=True)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("配置必须是 JSON 兼容 YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("配置顶层必须是对象")
    if "qianwen_base_url" not in payload and os.environ.get("EVOWEAVE_QIANWEN_BASE_URL"):
        payload["qianwen_base_url"] = os.environ["EVOWEAVE_QIANWEN_BASE_URL"]
    return EvoWeaveConfig.model_validate(payload)
