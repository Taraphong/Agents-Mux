"""Provider reply assembly: keep every text part and notice a cut reply.

Gemini can answer in several parts, and reading only the first one returned a
fragment that ended mid-sentence with finishReason=STOP. A reply stopped by the
token budget or a safety block has to be flagged instead of looking complete.
"""

from core.providers import (
    CUT_FINISH_REASONS,
    gemini_text_parts,
    usage_with_finish_reason,
)


def test_every_text_part_is_joined():
    parts = [{"text": "สวัสดีครับ "}, {"text": "นี่คือรายงานอากาศ"}, {"text": " 30°C"}]
    assert gemini_text_parts(parts) == "สวัสดีครับ นี่คือรายงานอากาศ 30°C"


def test_thought_parts_are_skipped():
    parts = [
        {"text": "คิดอยู่", "thought": True},
        {"text": "คำตอบจริง"},
    ]
    assert gemini_text_parts(parts) == "คำตอบจริง"


def test_parts_without_text_or_of_another_type_are_ignored():
    parts = [{"inlineData": {"mimeType": "image/png"}}, {"text": ""}, {"text": "ok"}]
    assert gemini_text_parts(parts) == "ok"


def test_finish_reason_rides_with_the_usage():
    usage = {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    result = usage_with_finish_reason(usage, "MAX_TOKENS")
    assert result["finish_reason"] == "MAX_TOKENS"
    assert result["total_tokens"] == 30
    assert "finish_reason" not in usage


def test_a_missing_usage_still_carries_the_reason():
    assert usage_with_finish_reason(None, "STOP") == {"finish_reason": "STOP"}


def test_no_reason_keeps_the_usage_untouched():
    usage = {"total_tokens": 5}
    assert usage_with_finish_reason(usage, "") is usage
    assert usage_with_finish_reason(None, None) is None


def test_only_real_truncations_are_flagged():
    assert {"MAX_TOKENS", "SAFETY", "RECITATION"} <= CUT_FINISH_REASONS
    assert "STOP" not in CUT_FINISH_REASONS
    assert "end_turn" not in CUT_FINISH_REASONS
