from function_router.server import extract_user_text


def test_extract_user_text_plain_string() -> None:
    messages = [{"role": "user", "content": "turn the volume up"}]
    assert extract_user_text(messages) == "turn the volume up"


def test_extract_user_text_strips_openclaw_metadata() -> None:
    content = """
<relevant-memories>
memory block
</relevant-memories>
Sender (untrusted metadata): ```json
{"name":"alice"}
```
[Thu 2026-03-19 19:23 GMT+8] turn brightness down
""".strip()
    messages = [{"role": "user", "content": content}]

    assert extract_user_text(messages) == "turn brightness down"


def test_extract_user_text_strips_ingest_reply_assist_transcript_wrapper() -> None:
    content = """
<ingest-reply-assist>
The latest user input looks like a multi-speaker transcript used for memory ingestion.
Reply with 1-2 concise sentences to acknowledge or summarize key points.
Do not output NO_REPLY or an empty reply.
Do not fabricate facts beyond the provided transcript and recalled memories.
</ingest-reply-assist>
System: [2026-04-19 19:57:07 GMT+8] Xiaomai message from session zs8srxfmibq: 10秒后关机 zs8srxfmibq: 10秒后关机
    """.strip()
    messages = [{"role": "user", "content": content}]

    assert extract_user_text(messages) == "10秒后关机"


def test_extract_user_text_strips_single_line_ingest_reply_assist_wrapper() -> None:
    content = "<ingest-reply-assist> The latest user input looks like a multi-speaker transcript used for memory ingestion. Reply with 1-2 concise sentences to acknowledge or summarize key points. Do not output NO_REPLY or an empty reply. Do not fabricate facts beyond the provided transcript and recalled memories. </ingest-reply-assist> System: [2026-04-20 17:32:39 GMT+8] Xiaomai message from session 813i9k9q3iw: 亮度调整到29 813i9k9q3iw: 亮度调整到29"
    messages = [{"role": "user", "content": content}]

    assert extract_user_text(messages) == "亮度调整到29"


def test_extract_user_text_handles_case_insensitive_ingest_tag() -> None:
    content = "<INGEST-REPLY-ASSIST> summarize </INGEST-REPLY-ASSIST> System: [2026-04-20 17:32:39 GMT+8] Xiaomai message from session 813i9k9q3iw: 打开夜间模式 813i9k9q3iw: 打开夜间模式"
    messages = [{"role": "user", "content": content}]

    assert extract_user_text(messages) == "打开夜间模式"


def test_extract_user_text_handles_transcript_without_session_id() -> None:
    messages = [
        {
            "role": "user",
            "content": "System: [2026-04-20 17:32:39 GMT+8] Xiaomai message: 音量调到15",
        }
    ]

    assert extract_user_text(messages) == "音量调到15"


def test_extract_user_text_handles_user_said_transcript_variant() -> None:
    messages = [
        {
            "role": "user",
            "content": "User: [2026-04-20 17:32:39 GMT+8] Xiaomai said from session 813i9k9q3iw: 关闭蓝牙 813i9k9q3iw: 关闭蓝牙",
        }
    ]

    assert extract_user_text(messages) == "关闭蓝牙"


def test_extract_user_text_keeps_non_duplicate_session_suffix() -> None:
    messages = [
        {
            "role": "user",
            "content": "System: [2026-04-20 17:32:39 GMT+8] Xiaomai message from session 813i9k9q3iw: 提醒我 813i9k9q3iw: 明天开会",
        }
    ]

    assert extract_user_text(messages) == "提醒我 813i9k9q3iw: 明天开会"


def test_extract_user_text_from_multimodal_text_parts() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "[Thu 2026-03-19 19:23 GMT+8] set wallpaper"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            ],
        }
    ]

    assert extract_user_text(messages) == "set wallpaper"


def test_extract_user_text_uses_latest_user_message() -> None:
    messages = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "newer"},
    ]

    assert extract_user_text(messages) == "newer"


def test_extract_user_text_returns_none_for_null_content() -> None:
    assert extract_user_text([{"role": "user", "content": None}]) is None


def test_extract_user_text_returns_empty_string_for_empty_multimodal_text() -> None:
    messages = [{"role": "user", "content": [{"type": "text", "text": ""}]}]
    assert extract_user_text(messages) == ""


def test_extract_user_text_returns_none_when_no_user_message() -> None:
    assert extract_user_text([{"role": "assistant", "content": "x"}]) is None

