from pathlib import Path
import json
import subprocess

import pytest

from function_router import builtin_tools
from function_router.server import _validate_function_name, load_tools


def test_load_tools_valid_jsonl(tmp_path: Path) -> None:
    functions_path = tmp_path / "functions.jsonl"
    functions_path.write_text(
        '\n'.join(
            [
                '{"name":"system_control","parameters":{"type":"object"}}',
                '{"name":"wallpaper_control","parameters":{"type":"object"}}',
            ]
        ),
        encoding="utf-8",
    )

    tools = load_tools(functions_path)
    names = {tool["function"]["name"] for tool in tools}

    assert tools[0] == {
        "type": "function",
        "function": {"name": "system_control", "parameters": {"type": "object"}},
    }
    assert tools[1] == {
        "type": "function",
        "function": {"name": "wallpaper_control", "parameters": {"type": "object"}},
    }
    assert {"find", "ls", "cat", "grep", "sleep"} <= names


def test_load_tools_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="functions file not found"):
        load_tools(tmp_path / "missing.jsonl")


def test_load_tools_invalid_json_line(tmp_path: Path) -> None:
    functions_path = tmp_path / "functions.jsonl"
    functions_path.write_text('{"name":"ok"}\n{invalid}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="failed parsing"):
        load_tools(functions_path)


def test_load_tools_invalid_object_line(tmp_path: Path) -> None:
    functions_path = tmp_path / "functions.jsonl"
    functions_path.write_text('["not-an-object"]\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid function object"):
        load_tools(functions_path)


def test_load_tools_empty_file(tmp_path: Path) -> None:
    functions_path = tmp_path / "functions.jsonl"
    functions_path.write_text("", encoding="utf-8")

    tools = load_tools(functions_path)
    names = {tool["function"]["name"] for tool in tools}

    assert {"find", "ls", "cat", "grep", "sleep"} <= names


def test_builtin_schema_jsonl_lives_next_to_module() -> None:
    assert builtin_tools.BUILTIN_FUNCTIONS_PATH.name == "function-builtin.jsonl"
    assert builtin_tools.BUILTIN_FUNCTIONS_PATH.exists() is True


def test_load_tools_reads_builtin_chinese_description(tmp_path: Path) -> None:
    functions_path = tmp_path / "functions.jsonl"
    functions_path.write_text("", encoding="utf-8")

    tools = load_tools(functions_path)
    find_tool = next(tool for tool in tools if tool["function"]["name"] == "find")
    properties = find_tool["function"]["parameters"]["properties"]

    assert "查找文件或目录" in find_tool["function"]["description"]
    assert properties["name_patterns"]["type"] == "array"
    assert "通配符" in properties["name_patterns"]["description"]


def test_load_tools_keeps_single_definition_when_user_overrides_builtin(tmp_path: Path) -> None:
    functions_path = tmp_path / "functions.jsonl"
    functions_path.write_text(
        '{"name":"find","description":"custom find","parameters":{"type":"object"}}\n',
        encoding="utf-8",
    )

    tools = load_tools(functions_path)
    find_tools = [tool for tool in tools if tool["function"]["name"] == "find"]

    assert len(find_tools) == 1
    assert find_tools[0]["function"]["description"] == "custom find"


def test_display_wrapper_inherits_desktop_session_env(tmp_path: Path) -> None:
    script_path = tmp_path / "display_control.sh"
    tool_root = tmp_path / "tools"
    tool_path = tool_root / "display-control" / "scripts" / "display-control.py"

    script_path.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "[ -z \"${FR_TOOLS_BASE_DIR:-}\" ] && exit 10\n"
        "TOOL_PATH=\"${FR_TOOLS_BASE_DIR}/display-control/scripts/display-control.py\"\n"
        "[ ! -f \"$TOOL_PATH\" ] && exit 11\n"
        "load_desktop_session_env() {\n"
        "    local shell_pid environ_file key value uid xauth_candidate\n"
        "    if [ -n \"${GNOME_SHELL_PID_FILE:-}\" ] && [ -r \"${GNOME_SHELL_PID_FILE}\" ]; then\n"
        "        shell_pid=$(tr -d \'\\n\' < \"${GNOME_SHELL_PID_FILE}\")\n"
        "    else\n"
        "        shell_pid=$(pgrep -n gnome-shell || true)\n"
        "    fi\n"
        "    if [ -n \"${GNOME_ENV_FILE:-}\" ] && [ -r \"${GNOME_ENV_FILE}\" ]; then\n"
        "        environ_file=\"${GNOME_ENV_FILE}\"\n"
        "    elif [ -n \"$shell_pid\" ] && [ -r \"/proc/$shell_pid/environ\" ]; then\n"
        "        environ_file=\"/proc/$shell_pid/environ\"\n"
        "    else\n"
        "        environ_file=\"\"\n"
        "    fi\n"
        "    if [ -n \"$environ_file\" ]; then\n"
        "        while IFS='=' read -r key value; do\n"
        "            case \"$key\" in\n"
        "                DISPLAY) [ -z \"${DISPLAY:-}\" ] && export DISPLAY=\"$value\" ;;\n"
        "                WAYLAND_DISPLAY) [ -z \"${WAYLAND_DISPLAY:-}\" ] && export WAYLAND_DISPLAY=\"$value\" ;;\n"
        "                XDG_RUNTIME_DIR) [ -z \"${XDG_RUNTIME_DIR:-}\" ] && export XDG_RUNTIME_DIR=\"$value\" ;;\n"
        "                DBUS_SESSION_BUS_ADDRESS) [ -z \"${DBUS_SESSION_BUS_ADDRESS:-}\" ] && export DBUS_SESSION_BUS_ADDRESS=\"$value\" ;;\n"
        "                XAUTHORITY) [ -z \"${XAUTHORITY:-}\" ] && export XAUTHORITY=\"$value\" ;;\n"
        "            esac\n"
        "        done < <(tr \'\\0\' \'\\n\' < \"$environ_file\")\n"
        "    fi\n"
        "    uid=$(id -u)\n"
        "    [ -z \"${XDG_RUNTIME_DIR:-}\" ] && [ -d \"/run/user/$uid\" ] && export XDG_RUNTIME_DIR=\"/run/user/$uid\"\n"
        "    [ -z \"${DBUS_SESSION_BUS_ADDRESS:-}\" ] && [ -n \"${XDG_RUNTIME_DIR:-}\" ] && [ -S \"${XDG_RUNTIME_DIR}/bus\" ] && export DBUS_SESSION_BUS_ADDRESS=\"unix:path=${XDG_RUNTIME_DIR}/bus\"\n"
        "    [ -z \"${DISPLAY:-}\" ] && [ -n \"$shell_pid\" ] && export DISPLAY=\":0\"\n"
        "    [ -z \"${WAYLAND_DISPLAY:-}\" ] && [ -n \"${XDG_RUNTIME_DIR:-}\" ] && [ -S \"${XDG_RUNTIME_DIR}/wayland-0\" ] && export WAYLAND_DISPLAY=\"wayland-0\"\n"
        "    if [ -z \"${XAUTHORITY:-}\" ] && [ -n \"${XDG_RUNTIME_DIR:-}\" ]; then\n"
        "        xauth_candidate=$(find \"${XDG_RUNTIME_DIR}\" -maxdepth 1 -name \'.mutter-Xwaylandauth.*\' -print -quit 2>/dev/null || true)\n"
        "        [ -n \"$xauth_candidate\" ] && export XAUTHORITY=\"$xauth_candidate\"\n"
        "    fi\n"
        "}\n"
        "load_desktop_session_env\n"
        "python3 \"$TOOL_PATH\"\n",
        encoding="utf-8",
    )
    script_path.chmod(0o755)

    tool_path.parent.mkdir(parents=True)
    tool_path.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "print(json.dumps({k: os.environ.get(k) for k in [\"DISPLAY\", \"WAYLAND_DISPLAY\", \"XDG_RUNTIME_DIR\", \"DBUS_SESSION_BUS_ADDRESS\", \"XAUTHORITY\"]}))\n",
        encoding="utf-8",
    )
    tool_path.chmod(0o755)

    gnome_env_file = tmp_path / "gnome.environ"
    gnome_env_file.write_bytes(
        b"DISPLAY=:99\0WAYLAND_DISPLAY=wayland-test\0XDG_RUNTIME_DIR=/tmp/runtime-test\0DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/runtime-test/bus\0XAUTHORITY=/tmp/.Xauthority-test\0"
    )

    gnome_pid_file = tmp_path / "gnome.pid"
    gnome_pid_file.write_text("12345\n", encoding="utf-8")

    result = subprocess.run(
        [str(script_path)],
        input='{"category":"display","action":"list"}',
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "FR_TOOLS_BASE_DIR": str(tool_root),
            "GNOME_ENV_FILE": str(gnome_env_file),
            "GNOME_SHELL_PID_FILE": str(gnome_pid_file),
        },
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == (
        '{"DISPLAY": ":99", "WAYLAND_DISPLAY": "wayland-test", '
        '"XDG_RUNTIME_DIR": "/tmp/runtime-test", '
        '"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/runtime-test/bus", '
        '"XAUTHORITY": "/tmp/.Xauthority-test"}'
    )


def test_builtin_find_supports_multiple_name_patterns(tmp_path: Path) -> None:
    (tmp_path / "clip.mp4").write_text("video", encoding="utf-8")
    (tmp_path / "movie.avi").write_text("video", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("text", encoding="utf-8")

    result = builtin_tools.execute_builtin_tool(
        "find",
        json.dumps({"path": str(tmp_path), "name_patterns": ["*.mp4", "*.avi"], "entry_type": "file"}),
        5,
    )

    assert result["result"] == "ok"
    assert sorted(Path(match).name for match in result["matches"]) == ["clip.mp4", "movie.avi"]
    assert "\\( -iname '*.mp4' -o -iname '*.avi' \\)" in result["command"]


def test_builtin_find_splits_space_separated_name_pattern(tmp_path: Path) -> None:
    (tmp_path / "clip.mp4").write_text("video", encoding="utf-8")
    (tmp_path / "movie.avi").write_text("video", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("text", encoding="utf-8")

    result = builtin_tools.execute_builtin_tool(
        "find",
        json.dumps({"path": str(tmp_path), "name_pattern": "*.mp4 *.avi", "entry_type": "file"}),
        5,
    )

    assert result["result"] == "ok"
    assert sorted(Path(match).name for match in result["matches"]) == ["clip.mp4", "movie.avi"]
    assert "-iname '*.mp4 *.avi'" not in result["command"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("system_control", True),
        ("system1", True),
        ("with-dash", False),
        ("../escape", False),
        ("space name", False),
        ("", False),
    ],
)
def test_validate_function_name(name: str, expected: bool) -> None:
    assert _validate_function_name(name) is expected
