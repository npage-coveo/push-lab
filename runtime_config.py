from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = "pushlab.yaml"


@dataclass(frozen=True)
class RuntimeConfig:
    scenario_file: str = "scenarios.json"
    max_retries: int = 5
    backoff_base_seconds: float = 1.0
    log_dir: str = "logs/payloads"
    default_queue_delay: int = 15
    request_timeout_seconds: int = 30
    upload_timeout_seconds: int = 120
    default_compression_type: str = "ZLib"


def load_runtime_config(config_path: str | None = None) -> RuntimeConfig:
    resolved_path = Path(config_path or DEFAULT_CONFIG_PATH)
    if not resolved_path.exists():
        if config_path:
            raise FileNotFoundError(f"Config file not found: {resolved_path}")
        return RuntimeConfig()

    with resolved_path.open("r", encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file) or {}

    if not isinstance(raw_config, dict):
        raise ValueError(f"Config file must contain a YAML object: {resolved_path}")

    return RuntimeConfig(
        scenario_file=_get_typed_value(raw_config, "scenario_file", str, resolved_path, "scenarios.json"),
        max_retries=_get_typed_value(raw_config, "max_retries", int, resolved_path, 5),
        backoff_base_seconds=_get_float_value(raw_config, "backoff_base_seconds", resolved_path, 1.0),
        log_dir=_get_typed_value(raw_config, "log_dir", str, resolved_path, "logs/payloads"),
        default_queue_delay=_get_typed_value(raw_config, "default_queue_delay", int, resolved_path, 15),
        request_timeout_seconds=_get_typed_value(raw_config, "request_timeout_seconds", int, resolved_path, 30),
        upload_timeout_seconds=_get_typed_value(raw_config, "upload_timeout_seconds", int, resolved_path, 120),
        default_compression_type=_get_typed_value(
            raw_config,
            "default_compression_type",
            str,
            resolved_path,
            "ZLib",
        ),
    )


def _get_typed_value(
    raw_config: dict[str, Any],
    key: str,
    expected_type: type,
    config_path: Path,
    default: Any,
) -> Any:
    value = raw_config.get(key, default)
    if not isinstance(value, expected_type):
        raise ValueError(
            f"Config key '{key}' in {config_path} must be a {expected_type.__name__}"
        )
    return value


def _get_float_value(
    raw_config: dict[str, Any],
    key: str,
    config_path: Path,
    default: float,
) -> float:
    value = raw_config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Config key '{key}' in {config_path} must be a number")
    return float(value)
