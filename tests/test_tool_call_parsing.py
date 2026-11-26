"""Tool-call parsing: the shapes small models really emit must not be lost.

A reply used to be shown to the user as raw ``<tool_call>`` text whenever the
payload was not exactly ``{"name": ..., "arguments": {...}}`` or the closing
marker was missing, because nothing ran and the text was returned as the answer.
"""

import pytest

from core.redaction import redact_secrets
from core.tools import has_tool_marker, parse_tool_requests, strip_tool_markers


def test_canonical_call_is_parsed():
    answer = '<tool_call>{"name":"run_command","arguments":{"command":"curl -s https://example.org"}}</tool_call>'
    assert parse_tool_requests(answer) == [
        {"name": "run_command", "arguments": {"command": "curl -s https://example.org"}}
    ]


def test_unnamed_command_becomes_run_command():
    answer = '<tool_call>{"command": "curl -s https://example.org"}</tool_call>'
    assert parse_tool_requests(answer) == [
        {"name": "run_command", "arguments": {"command": "curl -s https://example.org"}}
    ]


def test_arguments_beside_the_name_are_kept():
    answer = '<tool_call>{"name":"run_command","command":"ls -la"}</tool_call>'
    assert parse_tool_requests(answer) == [
        {"name": "run_command", "arguments": {"command": "ls -la"}}
    ]


def test_a_complete_payload_without_the_closing_marker_still_runs():
    answer = '<tool_call>{"name":"list_files","arguments":{"path":"~"}}'
    assert parse_tool_requests(answer) == [
        {"name": "list_files", "arguments": {"path": "~"}}
    ]


def test_a_cut_off_payload_raises_so_the_turn_can_be_repaired():
    answer = '<tool_call>{"name":"run_command","arguments":{"command":"curl -s \\"https://exa'
    with pytest.raises(ValueError):
        parse_tool_requests(answer)


def test_a_payload_without_a_name_or_command_raises():
    with pytest.raises(ValueError):
        parse_tool_requests('<tool_call>{"arguments":{"path":"~"}}</tool_call>')


def test_plain_text_is_not_a_tool_call():
    assert parse_tool_requests("อุณหภูมิวันนี้ 32°C") == []
    assert strip_tool_markers("อุณหภูมิวันนี้ 32°C") == "อุณหภูมิวันนี้ 32°C"


def test_markers_are_stripped_from_user_facing_text():
    answer = 'ก่อนรัน\n<tool_call>{"name":"run_command","arguments":{"command":"ls"}}</tool_call>\nหลังรัน'
    assert strip_tool_markers(answer) == "ก่อนรัน\n\nหลังรัน"


def test_a_key_in_the_reply_is_redacted():
    text = redact_secrets(
        "curl 'https://api.openweathermap.org/data/2.5/weather?q=X&appid=abcdef0123456789'"
    )
    assert "abcdef0123456789" not in text
    assert "appid=••••••••" in text


def test_a_dangling_marker_drops_its_tail():
    answer = 'เริ่มแล้ว\n<tool_call>{"command":"curl -s https://example.org?appid=abc'
    assert strip_tool_markers(answer) == "เริ่มแล้ว"
    assert strip_tool_markers('<tool_call>{"command":"ls"') == ""
    assert not has_tool_marker(strip_tool_markers(answer))


def test_a_closing_marker_inside_a_json_string_does_not_end_the_block():
    answer = 'ก่อนรัน\n<tool_call>{"command":"echo </tool_call>"}</tool_call>\nหลังรัน'
    assert strip_tool_markers(answer) == "ก่อนรัน\n\nหลังรัน"
    assert parse_tool_requests(answer) == [
        {"name": "run_command", "arguments": {"command": "echo </tool_call>"}}
    ]
