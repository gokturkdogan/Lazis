"""Layered configuration loading: model defaults → user TOML → ``LAZIS_*`` env → CLI overrides.

Validation errors are converted to :class:`ConfigError` with field paths and reasons only;
configuration *values* are never echoed (they could contain paths or other local details).
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lazis.config.model import Settings
from lazis.errors import ConfigError

ENV_PREFIX = "LAZIS_"


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)  # pyright: ignore[reportUnknownArgumentType]
        else:
            merged[key] = value
    return merged


def _parse_env_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """``LAZIS_BACKEND__RATE_LIMIT_BURST=10`` → ``{"backend": {"rate_limit_burst": 10}}``."""
    result: dict[str, Any] = {}
    for name, raw in environ.items():
        if not name.startswith(ENV_PREFIX) or "__" not in name:
            continue
        section, _, field = name[len(ENV_PREFIX) :].lower().partition("__")
        if section and field:
            result.setdefault(section, {})[field] = _parse_env_value(raw)
    return result


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        # Report the position only; the parser message may quote file content.
        position = re.search(r"line \d+, column \d+", str(exc))
        where = f" ({position.group(0)})" if position else ""
        raise ConfigError(f"user config is not valid TOML{where}") from None
    except OSError as exc:
        raise ConfigError(f"user config could not be read ({exc.__class__.__name__})") from None


def load_settings(
    *,
    user_config: Path | None = None,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    data: dict[str, Any] = {}
    if user_config is not None and user_config.exists():
        data = _deep_merge(data, _read_toml(user_config))
    if environ is not None:
        data = _deep_merge(data, env_overrides(environ))
    if overrides:
        data = _deep_merge(data, overrides)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(problems) from None
