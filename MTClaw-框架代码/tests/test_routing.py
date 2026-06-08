import json
from pathlib import Path

import pytest

from function_router import server


@pytest.fixture(autouse=True)
def restore_state() -> None:
    old_config = server.STATE.config
    old_tools = server.STATE.tools
    old_http_client = server.STATE.http_client
    try:
        yield
    finally:
        server.STATE.config = old_config
        server.STATE.tools = old_tools
        server.STATE.http_client = old_http_client


def make_config(max_tool_rounds: int = 3) -> server.AppConfig:
    return server.AppConfig(
        listen_host="127.0.0.1",
        listen_port=18790,
        routing=server.ModelConfig("http://router/v1", "router", "any"),
        upstream=server.ModelConfig("http://upstream/v1", "upstream", "secret"),
        functions_file="functions.jsonl",
        scripts_dir="scripts",
        max_tool_rounds=max_tool_rounds,
        tool_exec_timeout_s=30,
        root_dir=server.Path("/tmp/function-router-tests"),
        config_path=server.Path("/tmp/function-router-tests/config.json"),
    )


def make_temp_config(root_dir: Path, max_tool_rounds: int = 3) -> server.AppConfig:
    return server.AppConfig(
        listen_host="127.0.0.1",
        listen_port=18790,
        routing=server.ModelConfig("http://router/v1", "router", "any"),
        upstream=server.ModelConfig("http://upstream/v1", "upstream", "secret"),
        functions_file="functions.jsonl",
        scripts_dir="scripts",
        max_tool_rounds=max_tool_rounds,
        tool_exec_timeout_s=30,
        root_dir=root_dir,
        config_path=root_dir / "config.json",
    )


@pytest.mark.asyncio
async def test_run_tool_loop_returns_no_tool_context_when_no_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server.STATE.config = make_config()
    server.STATE.tools = [{"type": "function", "function": {"name": "system_control"}}]

    async def fake_call_qwen(messages):
        return {"choices": [{"message": {"content": "cannot handle"}}]}

    monkeypatch.setattr(server, "call_qwen", fake_call_qwen)

    result = await server.run_tool_loop("hello")

    assert result.used_any_tool is False
    assert result.last_function_name is None
    assert result.tool_context == []
    assert result.max_rounds_exhausted is False


@pytest.mark.asyncio
async def test_run_tool_loop_single_tool_call_normalizes_null_content_and_missing_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server.STATE.config = make_config()
    server.STATE.tools = [{"type": "function", "function": {"name": "system_control"}}]
    calls = [
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "system_control",
                                    "arguments": '{"category":"volume","action":"status"}',
                                }
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "done"}}]},
    ]

    async def fake_call_qwen(messages):
        return calls.pop(0)

    async def fake_execute_tool(function_name: str, arguments_json: str):
        assert function_name == "system_control"
        assert '"status"' in arguments_json
        return {"success": True, "current_value": 50}

    monkeypatch.setattr(server, "call_qwen", fake_call_qwen)
    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    result = await server.run_tool_loop("check volume")

    assert result.used_any_tool is True
    assert result.last_function_name == "system_control"
    assert result.tool_rounds == 2
    assert result.max_rounds_exhausted is False
    assert result.tool_context[0] == {"role": "user", "content": "check volume"}
    assistant_context = result.tool_context[1]
    assert assistant_context["role"] == "assistant"
    assert assistant_context["content"] == ""
    assert assistant_context["tool_calls"][0]["function"] == {
        "name": "system_control",
        "arguments": '{"category":"volume","action":"status"}',
    }
    tool_context = result.tool_context[2]
    assert tool_context["role"] == "tool"
    assert tool_context["tool_call_id"] == "call_system_control_1"
    assert tool_context["name"] == "system_control"
    assert tool_context["content"] == '{"success": true, "current_value": 50}'


@pytest.mark.asyncio
async def test_run_tool_loop_multi_round_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    server.STATE.config = make_config(max_tool_rounds=3)
    server.STATE.tools = [{"type": "function", "function": {"name": "system_control"}}]
    calls = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_one",
                                "function": {
                                    "name": "system_control",
                                    "arguments": '{"category":"brightness","action":"status"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_two",
                                "function": {
                                    "name": "system_control",
                                    "arguments": '{"category":"brightness","action":"set","value":80}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "done"}}]},
    ]
    executed = []

    async def fake_call_qwen(messages):
        return calls.pop(0)

    async def fake_execute_tool(function_name: str, arguments_json: str):
        executed.append((function_name, arguments_json))
        return {"ok": True}

    monkeypatch.setattr(server, "call_qwen", fake_call_qwen)
    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    result = await server.run_tool_loop("make it brighter")

    assert result.used_any_tool is True
    assert result.tool_rounds == 3
    assert result.max_rounds_exhausted is False
    assert executed == [
        ("system_control", '{"category":"brightness","action":"status"}'),
        ("system_control", '{"category":"brightness","action":"set","value":80}'),
    ]
    assert [message["role"] for message in result.tool_context] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]


@pytest.mark.asyncio
async def test_run_tool_loop_returns_context_when_max_rounds_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server.STATE.config = make_config(max_tool_rounds=2)
    server.STATE.tools = [{"type": "function", "function": {"name": "wallpaper_control"}}]

    async def fake_call_qwen(messages):
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_loop",
                                "function": {
                                    "name": "wallpaper_control",
                                    "arguments": '{"action":"random"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

    async def fake_execute_tool(function_name: str, arguments_json: str):
        return {"success": True}

    monkeypatch.setattr(server, "call_qwen", fake_call_qwen)
    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    result = await server.run_tool_loop("random wallpaper")

    assert result.used_any_tool is True
    assert result.last_function_name == "wallpaper_control"
    assert result.tool_rounds == 2
    assert result.max_rounds_exhausted is True
    assert result.tool_context[-1]["role"] == "tool"


@pytest.mark.asyncio
async def test_execute_tool_builtin_find_does_not_require_script_file(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "movie.mp4").write_text("", encoding="utf-8")

    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool(
        "find",
        json.dumps({"path": str(media_dir), "name_pattern": "*.mp4"}),
    )

    assert result["result"] == "ok"
    assert str(media_dir / "movie.mp4") in result["tool_output"]


@pytest.mark.asyncio
async def test_execute_tool_builtin_find_expands_tilde_to_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    home_dir = tmp_path / "home"
    (home_dir / "music").mkdir(parents=True)
    (home_dir / "music" / "song.mp3").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home_dir))

    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool(
        "find",
        json.dumps({"path": "~", "name_pattern": "*.mp3", "entry_type": "file"}),
    )

    assert result["result"] == "ok"
    assert str(home_dir / "music" / "song.mp3") in result["matches"]


@pytest.mark.asyncio
async def test_execute_tool_builtin_find_reports_missing_path_error(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool(
        "find",
        json.dumps({"path": str(tmp_path / "missing"), "name_pattern": "*.mp3"}),
    )

    assert result["error"]
    assert result["returncode"] != 0


@pytest.mark.asyncio
async def test_execute_tool_builtin_cat_returns_file_content(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    note_path = tmp_path / "note.txt"
    note_path.write_text("alpha\nbeta\n", encoding="utf-8")

    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool(
        "cat",
        json.dumps({"path": str(note_path)}),
    )

    assert result["result"] == "ok"
    assert result["tool_output"] == "alpha\nbeta"


@pytest.mark.asyncio
async def test_execute_tool_builtin_ls_lists_directory_contents(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "a.mp4").write_text("", encoding="utf-8")
    (media_dir / "b.txt").write_text("", encoding="utf-8")

    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool("ls", json.dumps({"path": str(media_dir)}))

    assert result["result"] == "ok"
    assert result["entries"] == ["a.mp4", "b.txt"]


@pytest.mark.asyncio
async def test_execute_tool_builtin_grep_matches_text(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    note_path = tmp_path / "note.txt"
    note_path.write_text("alpha\nbeta keyword\n", encoding="utf-8")

    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool(
        "grep",
        json.dumps({"path": str(note_path), "pattern": "keyword"}),
    )

    assert result["result"] == "ok"
    assert result["matches"] == [f"2:beta keyword"]


@pytest.mark.asyncio
async def test_execute_tool_builtin_sleep_validates_seconds(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool("sleep", json.dumps({"seconds": -1}))

    assert result["error"] == "seconds must be a non-negative number"


def test_system_prompt_requires_verbatim_copy_of_tool_values() -> None:
    prompt = server.SYSTEM_PROMPT
    assert "copy that value verbatim exactly as it appears" in prompt
    assert "Never replace any part of an exact value with ellipsis" in prompt
    assert "If the exact value is missing or ambiguous, do not guess" in prompt
    assert "Never substitute visually similar Unicode characters" in prompt
    assert "Cyrillic or Greek letters" in prompt


@pytest.mark.asyncio
async def test_execute_tool_non_builtin_still_requires_script_file(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    server.STATE.config = make_temp_config(tmp_path)

    result = await server.execute_tool("custom_tool", json.dumps({"path": "/tmp"}))

    assert result["error"] == "script not found: custom_tool.sh"


class _StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _StubHttpClient:
    """Records call timeouts and replays a scripted sequence of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0
        self.timeouts_seen: list[float] = []

    async def post(self, url, json=None, headers=None, timeout=None):
        import httpx

        self.call_count += 1
        self.timeouts_seen.append(timeout)
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _StubResponse(item)


@pytest.mark.asyncio
async def test_call_qwen_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config()
    config.routing_timeout_s = 15.0
    server.STATE.config = config
    server.STATE.tools = []
    client = _StubHttpClient([{"choices": [{"message": {"content": "ok"}}]}])
    server.STATE.http_client = client

    await server.call_qwen([{"role": "user", "content": "hi"}])

    assert client.call_count == 1
    assert client.timeouts_seen == [15.0]


@pytest.mark.asyncio
async def test_call_qwen_retries_once_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    server.STATE.config = make_config()
    server.STATE.tools = []
    client = _StubHttpClient([
        httpx.ReadTimeout("slow"),
        {"choices": [{"message": {"content": "recovered"}}]},
    ])
    server.STATE.http_client = client
    monkeypatch.setattr(server.asyncio, "sleep", lambda _s: _noop_sleep())

    result = await server.call_qwen([{"role": "user", "content": "hi"}])

    assert client.call_count == 2
    assert result["choices"][0]["message"]["content"] == "recovered"


@pytest.mark.asyncio
async def test_call_qwen_propagates_timeout_after_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    server.STATE.config = make_config()
    server.STATE.tools = []
    client = _StubHttpClient([
        httpx.ReadTimeout("slow"),
        httpx.ReadTimeout("still slow"),
    ])
    server.STATE.http_client = client
    monkeypatch.setattr(server.asyncio, "sleep", lambda _s: _noop_sleep())

    with pytest.raises(httpx.TimeoutException):
        await server.call_qwen([{"role": "user", "content": "hi"}])

    assert client.call_count == 2


async def _noop_sleep() -> None:
    return None
