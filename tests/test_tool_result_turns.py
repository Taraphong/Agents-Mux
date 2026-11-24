"""Approved tool results must read as a continuation, not as a new question.

The page used to send the tool output as a user turn, so the model answered it
with a fresh greeting and the raw JSON sat in the chat as if the user typed it.
"""

from routes.index import TOOL_RESULT_CONTINUATION, prepare_tool_result_turns


def test_tool_result_turn_is_wrapped_for_the_model():
    messages = [
        {"role": "user", "content": "อากาศมหาสารคาม"},
        {
            "role": "user",
            "content": 'Tool result:\n{"cod": 200}',
            "tool_result": True,
            "tool_name": "run_command",
        },
    ]
    prepared = prepare_tool_result_turns(messages)

    assert prepared[-1]["content"].startswith("The user approved the tool `run_command`")
    assert '{"cod": 200}' in prepared[-1]["content"]
    assert "tool_result" not in prepared[-1]
    # The page and the history still render the stored turn unchanged.
    assert messages[-1]["content"] == 'Tool result:\n{"cod": 200}'


def test_plain_turns_are_kept_as_they_are():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert prepare_tool_result_turns(messages) == messages


def test_a_result_without_a_tool_name_still_produces_a_turn():
    prepared = prepare_tool_result_turns(
        [{"role": "user", "content": "{}", "tool_result": True}]
    )
    assert prepared[0]["role"] == "user"
    assert prepared[0]["content"].startswith("The user approved the tool `a tool`")


def test_empty_output_does_not_break_the_wrapper():
    prepared = prepare_tool_result_turns(
        [{"role": "user", "content": "", "tool_result": True, "tool_name": "list_files"}]
    )
    assert prepared[0]["content"].endswith("unless it is the answer.")


def test_braces_in_the_output_are_not_formatted_again():
    output = 'Tool result:\n{"nested": {"a": 1}}'
    prepared = prepare_tool_result_turns(
        [{"role": "user", "content": output, "tool_result": True, "tool_name": "read_file"}]
    )
    assert output in prepared[0]["content"]
    assert "{" not in TOOL_RESULT_CONTINUATION.replace("{name}", "").replace("{output}", "")
