from __future__ import annotations

from pathlib import Path

import pytest

from lazis.config import Settings, load_settings
from lazis.config.loader import env_overrides
from lazis.errors import ConfigError


def test_defaults_are_privacy_preserving() -> None:
    s = Settings()
    assert s.backend.host == "127.0.0.1"
    assert s.backend.port == 0  # OS-assigned, collision-safe
    assert s.research.mode == "offline_only"
    assert s.network.egress_enabled is False
    assert s.voice.enabled is False
    assert s.voice.microphone_always_on is False
    assert s.models.primary_model == "gemma4:12b-it-qat"  # provisional P2 choice
    assert s.models.context_short == s.models.context_normal == 16384  # no reloads between them
    assert s.effective_origins() == ("tauri://localhost",)


def test_dev_environment_adds_vite_origin_only_in_development() -> None:
    s = load_settings(overrides={"app": {"environment": "development"}})
    assert "http://localhost:1420" in s.effective_origins()
    assert "http://localhost:1420" not in load_settings().effective_origins()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "localhost", "example.com", ""])
def test_non_loopback_hosts_are_rejected(host: str) -> None:
    with pytest.raises(ConfigError, match=r"backend\.host"):
        load_settings(overrides={"backend": {"host": host}})


def test_ipv6_loopback_is_accepted() -> None:
    assert load_settings(overrides={"backend": {"host": "::1"}}).backend.host == "::1"


@pytest.mark.parametrize("mode", ["ask_per_session", "auto_public", "custom"])
def test_research_modes_other_than_offline_are_rejected_before_p12(mode: str) -> None:
    with pytest.raises(ConfigError, match=r"research\.mode"):
        load_settings(overrides={"research": {"mode": mode}})


def test_network_egress_and_voice_cannot_be_enabled() -> None:
    with pytest.raises(ConfigError):
        load_settings(overrides={"network": {"egress_enabled": True}})
    with pytest.raises(ConfigError):
        load_settings(overrides={"voice": {"enabled": True}})
    with pytest.raises(ConfigError):
        load_settings(overrides={"voice": {"microphone_always_on": True}})


def test_models_endpoint_must_be_loopback() -> None:
    with pytest.raises(ConfigError, match=r"models\.endpoint"):
        load_settings(overrides={"models": {"endpoint": "https://api.example.com"}})


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ConfigError, match="(?i)extra"):
        load_settings(overrides={"backend": {"bind_everywhere": True}})


def test_layering_user_toml_then_env_then_overrides(tmp_path: Path) -> None:
    user = tmp_path / "config.toml"
    user.write_text('[logging]\nlevel = "DEBUG"\n[backend]\nrate_limit_burst = 7\n')
    env = {"LAZIS_BACKEND__RATE_LIMIT_BURST": "9", "UNRELATED": "x"}
    s = load_settings(user_config=user, environ=env, overrides={"storage": {"backups_keep": 3}})
    assert s.logging.level == "DEBUG"  # from TOML
    assert s.backend.rate_limit_burst == 9  # env beats TOML
    assert s.storage.backups_keep == 3  # CLI override


def test_invalid_toml_reports_line_without_content(tmp_path: Path) -> None:
    user = tmp_path / "config.toml"
    user.write_text('[backend]\nhost = "SECRET-VALUE\n')
    with pytest.raises(ConfigError) as info:
        load_settings(user_config=user)
    assert "SECRET-VALUE" not in str(info.value.detail)


def test_validation_errors_do_not_echo_values() -> None:
    with pytest.raises(ConfigError) as info:
        load_settings(overrides={"backend": {"host": "10.9.8.7"}})
    assert "10.9.8.7" not in info.value.detail


def test_env_override_parsing() -> None:
    assert env_overrides({"LAZIS_LOGGING__CONSOLE": "true", "LAZIS_X": "1"}) == {
        "logging": {"console": True}
    }
