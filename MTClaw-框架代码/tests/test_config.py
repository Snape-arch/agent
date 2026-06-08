import json
from pathlib import Path

import pytest

from function_router.server import (
    AppConfig,
    COMPLETION_CHECK_PROMPT_PERMISSIVE,
    COMPLETION_CHECK_PROMPT_STRICT,
    ModelConfig,
    get_completion_check_prompt,
    load_config,
    substitute_env_vars,
)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def valid_config_payload() -> dict:
    return {
        "listen_host": "127.0.0.1",
        "listen_port": 18790,
        "routing": {
            "base_url": "http://localhost:8080/v1",
            "model": "router-model",
            "api_key": "any",
        },
        "upstream": {
            "base_url": "https://example.com/v1",
            "api_key": "secret",
            "model": "upstream-model",
        },
        "functions_file": "functions.jsonl",
        "scripts_dir": "scripts",
        "max_tool_rounds": 3,
        "tool_exec_timeout_s": 30,
    }


def test_substitute_env_vars_recurses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSTREAM_API_KEY", "resolved-value")

    payload = {
        "single": "${UPSTREAM_API_KEY}",
        "nested": ["x", {"token": "${UPSTREAM_API_KEY}"}],
    }

    assert substitute_env_vars(payload) == {
        "single": "resolved-value",
        "nested": ["x", {"token": "resolved-value"}],
    }


def test_load_config_valid(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    write_json(config_path, valid_config_payload())

    config = load_config(config_path)

    assert isinstance(config, AppConfig)
    assert config.listen_host == "127.0.0.1"
    assert config.listen_port == 18790
    assert config.routing == ModelConfig(
        base_url="http://localhost:8080/v1",
        model="router-model",
        api_key="any",
    )
    assert config.functions_path == tmp_path / "functions.jsonl"
    assert config.resolved_scripts_dir == tmp_path / "scripts"


def test_load_config_substitutes_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPSTREAM_API_KEY", "env-secret")
    payload = valid_config_payload()
    payload["upstream"]["api_key"] = "${UPSTREAM_API_KEY}"
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    config = load_config(config_path)

    assert config.upstream.api_key == "env-secret"


def test_load_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="config file not found"):
        load_config(tmp_path / "missing.json")


def test_load_config_invalid_json(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid config JSON"):
        load_config(config_path)


def test_load_config_missing_key(tmp_path: Path) -> None:
    payload = valid_config_payload()
    del payload["routing"]
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    with pytest.raises(RuntimeError, match="missing config key: routing"):
        load_config(config_path)


def test_load_config_accepts_legacy_qwen_key(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["qwen"] = payload.pop("routing")
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    config = load_config(config_path)

    assert config.routing == ModelConfig(
        base_url="http://localhost:8080/v1",
        model="router-model",
        api_key="any",
    )


def test_load_config_prefers_routing_over_legacy_qwen(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["qwen"] = {
        "base_url": "http://legacy/v1",
        "model": "legacy-router",
        "api_key": "legacy",
    }
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    config = load_config(config_path)

    assert config.routing == ModelConfig(
        base_url="http://localhost:8080/v1",
        model="router-model",
        api_key="any",
    )


def test_load_config_defaults_completion_check_mode(tmp_path: Path) -> None:
    payload = valid_config_payload()
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    config = load_config(config_path)

    assert config.fr_completion_check is True
    assert config.fr_completion_check_mode == "permissive"
    assert config.fr_completion_check_always_true is False
    assert config.fr_context_history is True


def test_load_config_accepts_completion_check_always_true(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["fr_completion_check"] = {"enabled": True, "always_true": True}
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    config = load_config(config_path)

    assert config.fr_completion_check is True
    assert config.fr_completion_check_always_true is True


def test_load_config_accepts_strict_completion_check_mode(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["fr_completion_check"] = {"enabled": True, "mode": "strict"}
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    config = load_config(config_path)

    assert config.fr_completion_check_mode == "strict"


def test_load_config_rejects_invalid_completion_check_mode(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["fr_completion_check"] = {"enabled": True, "mode": "aggressive"}
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    with pytest.raises(RuntimeError, match="invalid fr_completion_check.mode"):
        load_config(config_path)


def test_get_completion_check_prompt_for_modes() -> None:
    assert get_completion_check_prompt("permissive") == COMPLETION_CHECK_PROMPT_PERMISSIVE
    assert get_completion_check_prompt("strict") == COMPLETION_CHECK_PROMPT_STRICT


def test_load_config_invalid_structure(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["listen_port"] = "not-an-int"
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    with pytest.raises(RuntimeError, match="invalid config structure"):
        load_config(config_path)


def test_load_config_default_routing_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    write_json(config_path, valid_config_payload())

    config = load_config(config_path)

    assert config.routing_timeout_s == 10.0


def test_load_config_custom_routing_timeout(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["routing_timeout_s"] = 20
    config_path = tmp_path / "config.json"
    write_json(config_path, payload)

    config = load_config(config_path)

    assert config.routing_timeout_s == 20.0
