"""The approval placeholder must never be replayed to the provider.

The turn that only asks for a tool approval was saved as the assistant's answer
and sent back in the next request, so a small model read its own sentence and
repeated it instead of reporting the approved tool's result.
"""

from core.config import APPROVAL_PLACEHOLDER
from routes.index import prepare_tool_result_turns


def test_the_approval_placeholder_is_dropped_before_the_provider():
    messages = [
        {"role": "user", "content": "รายงานสภาพอากาศ"},
        {"role": "assistant", "content": APPROVAL_PLACEHOLDER},
        {
            "role": "user",
            "content": "Tool result:\n{\"returncode\": 0}",
            "tool_result": True,
            "tool_name": "run_command",
        },
    ]
    prepared = prepare_tool_result_turns(messages)
    assert [item["role"] for item in prepared] == ["user", "user"]
    assert APPROVAL_PLACEHOLDER not in prepared[1]["content"]
    assert "The user approved the tool `run_command`" in prepared[1]["content"]


def test_the_placeholder_is_matched_even_with_padding():
    messages = [{"role": "assistant", "content": f"  {APPROVAL_PLACEHOLDER}\n"}]
    assert prepare_tool_result_turns(messages) == []


def test_a_real_answer_is_kept():
    messages = [
        {"role": "user", "content": "สวัสดี"},
        {"role": "assistant", "content": "สวัสดีครับ มีอะไรให้ช่วย"},
    ]
    assert prepare_tool_result_turns(messages) == messages
