import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path("/home/mt/zhenlin.liang/agent/git/openclaw-function-router")
SCRIPT_PATH = REPO_ROOT / "scripts" / "install.sh"


def run_install(tmp_path: Path, user_input: str) -> subprocess.CompletedProcess[str]:
    home_dir = tmp_path / "home"
    openclaw_dir = home_dir / ".openclaw"
    openclaw_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        env=env,
        input=user_input,
        text=True,
        capture_output=True,
        check=False,
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_install_uses_existing_openclaw_primary_as_upstream_default(tmp_path: Path) -> None:
    openclaw_config = tmp_path / "home" / ".openclaw" / "openclaw.json"
    openclaw_config.parent.mkdir(parents=True, exist_ok=True)
    openclaw_config.write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "doubao": {
                            "baseUrl": "https://ark.example/v1",
                            "apiKey": "existing-secret",
                            "api": "openai-completions",
                            "models": [{"id": "doubao-seed-2-0-pro", "name": "Doubao"}],
                        }
                    }
                },
                "agents": {"defaults": {"model": {"primary": "doubao/doubao-seed-2-0-pro"}}},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_install(
        tmp_path,
        "\n".join(
            [
                "y",
                "http://localhost:8080/v1",
                "router-model",
                "any",
                "18790",
                "/tmp/tools",
                str(openclaw_config),
                "",
            ]
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "Detected OpenClaw primary model: doubao/doubao-seed-2-0-pro" in result.stdout
    assert "检测到当前 OpenClaw 主模型: doubao/doubao-seed-2-0-pro" in result.stdout
    assert "Using detected upstream configuration as default." in result.stdout
    assert "将使用检测到的上游配置作为默认值。" in result.stdout
    assert "Base URL: https://ark.example/v1" in result.stdout
    assert "基础地址: https://ark.example/v1" in result.stdout
    assert "Model: doubao-seed-2-0-pro" in result.stdout
    assert "模型: doubao-seed-2-0-pro" in result.stdout

    config = load_json(tmp_path / "home" / ".function-router" / "config.json")
    assert config["upstream"] == {
        "base_url": "https://ark.example/v1",
        "api_key": "existing-secret",
        "model": "doubao-seed-2-0-pro",
    }


def test_install_prompts_for_upstream_when_declining_existing_primary(tmp_path: Path) -> None:
    openclaw_config = tmp_path / "home" / ".openclaw" / "openclaw.json"
    openclaw_config.parent.mkdir(parents=True, exist_ok=True)
    openclaw_config.write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "doubao": {
                            "baseUrl": "https://ark.example/v1",
                            "apiKey": "existing-secret",
                            "api": "openai-completions",
                            "models": [{"id": "doubao-seed-2-0-pro", "name": "Doubao"}],
                        }
                    }
                },
                "agents": {"defaults": {"model": {"primary": "doubao/doubao-seed-2-0-pro"}}},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_install(
        tmp_path,
        "\n".join(
            [
                "n",
                "http://localhost:8080/v1",
                "router-model",
                "any",
                "https://custom.example/v1",
                "custom-secret",
                "custom-model",
                "18790",
                "/tmp/tools",
                str(openclaw_config),
                "",
            ]
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "Detected OpenClaw primary model: doubao/doubao-seed-2-0-pro" in result.stdout
    assert "检测到当前 OpenClaw 主模型: doubao/doubao-seed-2-0-pro" in result.stdout
    assert "Using detected upstream configuration as default." not in result.stdout
    assert "将使用检测到的上游配置作为默认值。" not in result.stdout

    config = load_json(tmp_path / "home" / ".function-router" / "config.json")
    assert config["upstream"] == {
        "base_url": "https://custom.example/v1",
        "api_key": "custom-secret",
        "model": "custom-model",
    }


def test_reinstall_uses_existing_function_router_upstream_as_default(tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    openclaw_config = home_dir / ".openclaw" / "openclaw.json"
    openclaw_config.parent.mkdir(parents=True, exist_ok=True)
    openclaw_config.write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "function_router": {
                            "baseUrl": "http://127.0.0.1:18790/v1",
                            "apiKey": "any",
                            "api": "openai-completions",
                            "models": [{"id": "function-router", "name": "Function Router"}],
                        }
                    }
                },
                "agents": {"defaults": {"model": {"primary": "function_router/function-router"}}},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    fr_config = home_dir / ".function-router" / "config.json"
    fr_config.parent.mkdir(parents=True, exist_ok=True)
    fr_config.write_text(
        json.dumps(
            {
                "listen_host": "0.0.0.0",
                "listen_port": 18790,
                "tools_base_dir": "~/.function-router/scripts",
                "routing": {
                    "base_url": "http://localhost:8080/v1",
                    "model": "router-model",
                    "api_key": "any",
                },
                "upstream": {
                    "base_url": "https://ark.example/v1",
                    "api_key": "existing-secret",
                    "model": "doubao-seed-2-0-pro",
                },
                "functions_file": "functions.jsonl",
                "scripts_dir": "scripts",
                "max_tool_rounds": 6,
                "tool_exec_timeout_s": 30,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_install(
        tmp_path,
        "\n".join(
            [
                "y",
                "http://localhost:8080/v1",
                "router-model",
                "any",
                "18790",
                "/tmp/tools",
                str(openclaw_config),
                "",
            ]
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "Detected existing Function Router upstream config:" in result.stdout
    assert "检测到现有 Function Router 上游配置：" in result.stdout
    assert "Base URL: https://ark.example/v1" in result.stdout
    assert "基础地址: https://ark.example/v1" in result.stdout
    assert "Model: doubao-seed-2-0-pro" in result.stdout
    assert "模型: doubao-seed-2-0-pro" in result.stdout

    config = load_json(home_dir / ".function-router" / "config.json")
    assert config["upstream"] == {
        "base_url": "https://ark.example/v1",
        "api_key": "existing-secret",
        "model": "doubao-seed-2-0-pro",
    }
