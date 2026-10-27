from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence

from llm_gateway.services.audit_diff import (
    PrefixCandidate,
    ResponseSummary,
    bound_parameter_changes,
    build_turn_diff,
    canonical_message,
    canonical_text,
    classify_change,
    common_prefix_length,
    first_user_message_index,
    match_prefix_candidate,
    message_hash,
    message_hashes,
    message_preview,
    summarize_response,
    text_hash,
    truncate_snapshot,
)


def _message(role: str, content: object = None, **extra: object) -> dict[str, object]:
    message: dict[str, object] = {"role": role, "content": content}
    message.update(extra)
    return message


def _snapshot_bytes(messages: Sequence[Mapping[str, object]], response: str | None) -> int:
    payload = {"messages": list(messages), "response": response}
    return len(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


# --- canonical hashing -------------------------------------------------------


def test_message_hash_is_stable_across_dict_ordering() -> None:
    left = {
        "role": "assistant",
        "content": "hi",
        "name": "bot",
        "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
        ],
    }
    right = {
        "tool_calls": [
            {"function": {"arguments": "{}", "name": "f"}, "type": "function", "id": "1"}
        ],
        "name": "bot",
        "content": "hi",
        "role": "assistant",
    }

    assert message_hash(left) == message_hash(right)


def test_message_hash_changes_for_distinct_roles_content_and_tool_calls() -> None:
    base = _message("user", "same")
    assert message_hash(base) != message_hash(_message("assistant", "same"))
    assert message_hash(base) != message_hash(_message("user", "other"))
    assert message_hash(base) != message_hash(
        _message("user", "same", tool_calls=[{"id": "1", "type": "function"}])
    )


def test_canonical_message_ignores_fields_outside_the_canonical_set() -> None:
    with_extra = _message("user", "hi", extra_field=1, metadata={"x": 2})
    without_extra = _message("user", "hi")

    assert canonical_message(with_extra) == canonical_message(without_extra)
    assert json.loads(canonical_message(with_extra)) == {"role": "user", "content": "hi"}


def test_message_hashes_preserves_sequence_order() -> None:
    messages = [_message("system", "s"), _message("user", "u")]

    hashes = message_hashes(messages)

    assert hashes == [message_hash(messages[0]), message_hash(messages[1])]


def test_canonical_text_and_text_hash_handle_missing_text() -> None:
    assert canonical_text(None) == ""
    assert canonical_text("hello") == "hello"
    assert text_hash(None) is None
    assert text_hash("hello") == text_hash("hello")
    assert text_hash("hello") != text_hash("world")


def test_first_user_message_index_finds_first_user_turn() -> None:
    messages = [_message("system", "s"), _message("assistant", "a"), _message("user", "u")]

    assert first_user_message_index(messages) == 2
    assert first_user_message_index([_message("system", "s")]) is None


def test_common_prefix_length_stops_at_first_difference() -> None:
    assert common_prefix_length(["a", "b", "c"], ["a", "b", "d"]) == 2
    assert common_prefix_length(["a"], ["a", "b"]) == 1
    assert common_prefix_length([], ["a"]) == 0


# --- prefix matching --------------------------------------------------------


def _candidate(index: int, hashes: Sequence[str]) -> PrefixCandidate:
    return PrefixCandidate(
        request_id=f"req-{index}",
        session_id=f"session-{index}",
        turn_index=index,
        message_hashes=tuple(hashes),
    )


def _match(
    messages: Sequence[Mapping[str, object]],
    candidates: Sequence[PrefixCandidate],
):
    return match_prefix_candidate(
        current_messages=messages,
        current_hashes=message_hashes(messages),
        candidates=candidates,
    )


def test_prefix_match_rejects_shared_system_prompt_only() -> None:
    system = _message("system", "shared")
    user = _message("user", "hello")
    messages = [system, user]

    result = _match(messages, [_candidate(1, [message_hash(system)])])

    assert result.method == "new"
    assert result.candidate is None
    assert result.common_prefix == 0


def test_prefix_match_accepts_shared_system_and_first_user_turn() -> None:
    system = _message("system", "shared")
    user = _message("user", "hello")
    messages = [system, user]
    candidate = _candidate(3, message_hashes(messages))

    result = _match(messages, [candidate])

    assert result.method == "prefix"
    assert result.candidate == candidate
    assert result.common_prefix == 2


def test_prefix_match_prefers_longest_shared_prefix() -> None:
    system = _message("system", "shared")
    user = _message("user", "hello")
    assistant = _message("assistant", "hi")
    messages = [system, user, assistant]
    short = _candidate(1, message_hashes([system, user]))
    long = _candidate(2, message_hashes([system, user, assistant]))

    result = _match(messages, [short, long])

    assert result.candidate == long
    assert result.common_prefix == 3


def test_prefix_match_keeps_newest_candidate_on_tie() -> None:
    system = _message("system", "shared")
    user = _message("user", "hello")
    messages = [system, user]
    newest = _candidate(9, message_hashes([system, user]))
    older = _candidate(1, message_hashes([system, user]))

    result = _match(messages, [newest, older])

    assert result.candidate == newest


def test_prefix_match_returns_new_when_no_user_message_exists() -> None:
    messages = [_message("system", "shared")]
    candidate = _candidate(1, message_hashes(messages))

    result = _match(messages, [candidate])

    assert result.method == "new"
    assert result.candidate is None


def test_prefix_match_returns_new_without_candidates() -> None:
    messages = [_message("system", "s"), _message("user", "u")]

    result = _match(messages, [])

    assert result.method == "new"
    assert result.candidate is None


# --- change classification --------------------------------------------------


def test_classify_change_without_parent_is_new_session() -> None:
    assert classify_change(current_hashes=["a"], parent_hashes=None) == "new_session"


def test_classify_change_with_equal_hashes_is_regeneration() -> None:
    assert classify_change(current_hashes=["a", "b"], parent_hashes=["a", "b"]) == "regeneration"
    assert classify_change(current_hashes=[], parent_hashes=[]) == "regeneration"


def test_classify_change_when_parent_is_extended_is_continuation() -> None:
    assert (
        classify_change(current_hashes=["a", "b", "c"], parent_hashes=["a", "b"]) == "continuation"
    )


def test_classify_change_when_current_is_shortened_is_truncation() -> None:
    assert classify_change(current_hashes=["a", "b"], parent_hashes=["a", "b", "c"]) == "truncation"


def test_classify_change_with_equal_length_edit_is_edit() -> None:
    assert classify_change(current_hashes=["a", "x"], parent_hashes=["a", "b"]) == "edit"


# --- turn diff shapes -------------------------------------------------------


def _diff(
    *,
    change_type,
    current_messages: Sequence[Mapping[str, object]],
    parent_messages: Sequence[Mapping[str, object]] | None,
    current_params: Mapping[str, object] | None = None,
    parent_params: Mapping[str, object] | None = None,
    current_usage: Mapping[str, int] | None = None,
    parent_usage: Mapping[str, int] | None = None,
    current_response: ResponseSummary | None = None,
    parent_response: ResponseSummary | None = None,
    preview_chars: int = 160,
):
    parent_hashes = None if parent_messages is None else message_hashes(parent_messages)
    return build_turn_diff(
        change_type=change_type,
        current_messages=current_messages,
        current_hashes=message_hashes(current_messages),
        parent_messages=parent_messages,
        parent_hashes=parent_hashes,
        current_params=current_params if current_params is not None else {},
        parent_params=parent_params,
        current_usage=current_usage,
        parent_usage=parent_usage,
        current_response=current_response,
        parent_response=parent_response,
        preview_chars=preview_chars,
    )


def test_continuation_diff_reports_only_appended_messages() -> None:
    system = _message("system", "s")
    user = _message("user", "u")
    assistant = _message("assistant", "a")
    parent = [system, user]
    current = [system, user, assistant]

    diff = _diff(change_type="continuation", current_messages=current, parent_messages=parent)

    assert diff.common_prefix == 2
    assert diff.modified_messages == []
    assert diff.removed_messages == []
    assert [entry["index"] for entry in diff.added_messages] == [2]
    assert diff.added_messages[0]["role"] == "assistant"
    assert diff.added_messages[0]["hash"] == message_hash(assistant)
    assert diff.added_messages[0]["preview"] == "a"


def test_edit_diff_reports_replaced_message_and_both_tails() -> None:
    system = _message("system", "s")
    old_user = _message("user", "old question")
    old_assistant = _message("assistant", "old answer")
    new_user = _message("user", "new question")
    new_assistant = _message("assistant", "new answer")
    parent = [system, old_user, old_assistant]
    current = [system, new_user, new_assistant]

    diff = _diff(change_type="edit", current_messages=current, parent_messages=parent)

    assert diff.common_prefix == 1
    assert len(diff.modified_messages) == 1
    modified = diff.modified_messages[0]
    assert modified["index"] == 1
    assert modified["before_hash"] == message_hash(old_user)
    assert modified["after_hash"] == message_hash(new_user)
    assert modified["before_preview"] == "old question"
    assert modified["after_preview"] == "new question"
    assert [entry["index"] for entry in diff.removed_messages] == [2]
    assert [entry["index"] for entry in diff.added_messages] == [2]


def test_truncation_diff_reports_only_removed_tail() -> None:
    system = _message("system", "s")
    user = _message("user", "u")
    assistant = _message("assistant", "a")
    parent = [system, user, assistant]
    current = [system, user]

    diff = _diff(change_type="truncation", current_messages=current, parent_messages=parent)

    assert diff.common_prefix == 2
    assert diff.added_messages == []
    assert diff.modified_messages == []
    assert [entry["index"] for entry in diff.removed_messages] == [2]
    assert diff.removed_messages[0]["preview"] == "a"


def test_regeneration_diff_has_no_message_movements() -> None:
    messages = [_message("system", "s"), _message("user", "u"), _message("assistant", "a")]

    diff = _diff(change_type="regeneration", current_messages=messages, parent_messages=messages)

    assert diff.common_prefix == 3
    assert diff.added_messages == []
    assert diff.modified_messages == []
    assert diff.removed_messages == []


def test_new_session_diff_reports_all_messages_as_added() -> None:
    messages = [_message("system", "s"), _message("user", "u")]

    diff = _diff(change_type="new_session", current_messages=messages, parent_messages=None)

    assert diff.common_prefix == 0
    assert [entry["index"] for entry in diff.added_messages] == [0, 1]
    assert diff.removed_messages == []
    assert diff.modified_messages == []


def test_preview_is_limited_to_preview_chars_and_flattens_content_parts() -> None:
    system = _message("system", "s")
    user = _message(
        "user",
        [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}],
    )
    parent = [system]
    current = [system, user]

    diff = _diff(
        change_type="continuation",
        current_messages=current,
        parent_messages=parent,
        preview_chars=8,
    )

    preview = str(diff.added_messages[0]["preview"])
    assert preview == "hello wo"
    assert len(preview) == 8
    assert "world" not in preview


def test_message_preview_never_returns_more_than_the_limit() -> None:
    message = _message("user", "abcdefghij")

    assert message_preview(message, 4) == "abcd"
    assert message_preview(message, 0) == ""
    assert message_preview(message, 100) == "abcdefghij"


# --- parameter / usage / response diffs -------------------------------------


def test_parameter_changes_only_include_changed_fields() -> None:
    parent = {"model": "m", "temperature": 0.2, "max_tokens": 100}
    current = {"model": "m", "temperature": 0.7, "max_tokens": 100, "n": 2}

    diff = _diff(
        change_type="regeneration",
        current_messages=[],
        parent_messages=[],
        current_params=current,
        parent_params=parent,
    )

    assert diff.parameter_changes == {
        "temperature": {"from": 0.2, "to": 0.7},
        "n": {"from": None, "to": 2},
    }


def test_parameter_changes_treat_missing_and_null_as_equal() -> None:
    parent = {"model": "m", "seed": None, "stop": None}
    current = {"model": "m"}

    diff = _diff(
        change_type="regeneration",
        current_messages=[],
        parent_messages=[],
        current_params=current,
        parent_params=parent,
    )

    assert diff.parameter_changes == {}


def test_parameter_changes_detect_tools_changes() -> None:
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    diff = _diff(
        change_type="regeneration",
        current_messages=[],
        parent_messages=[],
        current_params={"tools": tools},
        parent_params={},
    )

    assert diff.parameter_changes == {"tools": {"from": None, "to": tools}}


def test_usage_delta_computes_per_field_differences_including_negatives() -> None:
    current = {"prompt_tokens": 10, "completion_tokens": 4, "cached_tokens": 1, "total_tokens": 14}
    parent = {"prompt_tokens": 8, "completion_tokens": 6, "cached_tokens": 3, "total_tokens": 14}

    diff = _diff(
        change_type="edit",
        current_messages=[],
        parent_messages=[],
        current_usage=current,
        parent_usage=parent,
    )

    assert diff.usage_delta == {
        "prompt_tokens": 2,
        "completion_tokens": -2,
        "cached_tokens": -2,
        "total_tokens": 0,
    }


def test_usage_delta_is_empty_without_a_parent_turn() -> None:
    diff = _diff(
        change_type="new_session",
        current_messages=[],
        parent_messages=None,
        current_usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        parent_usage=None,
    )

    assert diff.usage_delta == {}


def test_usage_delta_is_empty_without_current_usage() -> None:
    diff = _diff(
        change_type="regeneration",
        current_messages=[],
        parent_messages=[],
        current_usage=None,
        parent_usage={"prompt_tokens": 1},
    )

    assert diff.usage_delta == {}


def test_usage_delta_treats_missing_keys_as_zero() -> None:
    diff = _diff(
        change_type="regeneration",
        current_messages=[],
        parent_messages=[],
        current_usage={"prompt_tokens": 3},
        parent_usage={},
    )

    assert diff.usage_delta == {
        "prompt_tokens": 3,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
    }


def test_summarize_response_counts_tool_calls_and_hashes_content() -> None:
    tool_calls = [
        {"id": "1", "type": "function", "function": {"name": "lookup"}},
        {"id": "2", "type": "function", "function": {"name": "search"}},
    ]

    summary = summarize_response(
        content="answer", tool_calls=tool_calls, finish_reason="tool_calls"
    )

    assert summary.content_hash == text_hash("answer")
    assert summary.finish_reason == "tool_calls"
    assert summary.tool_call_count == 2
    assert summary.tool_call_names == ("lookup", "search")


def test_summarize_response_handles_missing_content_and_tools() -> None:
    summary = summarize_response(content=None, tool_calls=None, finish_reason=None)

    assert summary == ResponseSummary(
        content_hash=None,
        finish_reason=None,
        tool_call_count=0,
        tool_call_names=(),
    )


def test_response_change_reports_content_reason_and_tool_call_deltas() -> None:
    parent = summarize_response(
        content="old",
        tool_calls=[{"id": "1", "type": "function", "function": {"name": "lookup"}}],
        finish_reason="stop",
    )
    current = summarize_response(
        content="new",
        tool_calls=[
            {"id": "2", "type": "function", "function": {"name": "search"}},
            {"id": "3", "type": "function", "function": {"name": "fetch"}},
        ],
        finish_reason="tool_calls",
    )

    diff = _diff(
        change_type="regeneration",
        current_messages=[],
        parent_messages=[],
        current_response=current,
        parent_response=parent,
    )

    assert diff.response_change == {
        "content_changed": True,
        "previous_content_hash": text_hash("old"),
        "content_hash": text_hash("new"),
        "finish_reason_changed": True,
        "previous_finish_reason": "stop",
        "finish_reason": "tool_calls",
        "tool_calls_added": 1,
        "tool_calls_removed": 0,
        "tool_call_names": ["search", "fetch"],
    }


def test_response_change_reports_removed_tool_calls() -> None:
    parent = summarize_response(
        content="same",
        tool_calls=[
            {"id": "1", "type": "function", "function": {"name": "lookup"}},
            {"id": "2", "type": "function", "function": {"name": "search"}},
        ],
        finish_reason="stop",
    )
    current = summarize_response(content="same", tool_calls=None, finish_reason="stop")

    diff = _diff(
        change_type="truncation",
        current_messages=[],
        parent_messages=[],
        current_response=current,
        parent_response=parent,
    )

    assert diff.response_change["content_changed"] is False
    assert diff.response_change["finish_reason_changed"] is False
    assert diff.response_change["tool_calls_added"] == 0
    assert diff.response_change["tool_calls_removed"] == 2


def test_response_change_without_parent_is_neutral() -> None:
    current = summarize_response(content="first", tool_calls=None, finish_reason="stop")

    diff = _diff(
        change_type="new_session",
        current_messages=[],
        parent_messages=None,
        current_response=current,
        parent_response=None,
    )

    assert diff.response_change == {
        "content_changed": False,
        "previous_content_hash": None,
        "content_hash": None,
        "finish_reason_changed": False,
        "previous_finish_reason": None,
        "finish_reason": None,
        "tool_calls_added": 0,
        "tool_calls_removed": 0,
        "tool_call_names": [],
    }


# --- snapshot truncation ----------------------------------------------------


def test_truncate_snapshot_leaves_small_payload_unchanged() -> None:
    messages = [_message("system", "s"), _message("user", "hello")]
    original = [dict(message) for message in messages]

    snapshot = truncate_snapshot(messages=messages, response_content="hi", max_bytes=10_000)

    assert snapshot.truncated is False
    assert snapshot.messages == original
    assert snapshot.response_content == "hi"
    assert messages == original


def test_truncate_snapshot_caps_response_to_quarter_budget() -> None:
    messages = [_message("user", "short")]

    snapshot = truncate_snapshot(
        messages=messages,
        response_content="x" * 10_000,
        max_bytes=400,
    )

    assert snapshot.truncated is True
    assert snapshot.response_content is not None
    assert len(snapshot.response_content.encode("utf-8")) <= 400 // 4
    assert _snapshot_bytes(snapshot.messages, snapshot.response_content) <= 400


def test_truncate_snapshot_shrinks_message_text_and_marks_messages() -> None:
    messages = [_message("user", "x" * 1_000) for _ in range(4)]
    original = [dict(message) for message in messages]

    snapshot = truncate_snapshot(messages=messages, response_content=None, max_bytes=600)

    assert snapshot.truncated is True
    assert len(snapshot.messages) == 4
    assert all(message.get("truncated") is True for message in snapshot.messages)
    assert all(len(str(message["content"])) <= 75 for message in snapshot.messages)
    assert _snapshot_bytes(snapshot.messages, snapshot.response_content) <= 600
    assert messages == original


def test_truncate_snapshot_never_splits_multibyte_characters() -> None:
    messages = [_message("assistant", "ok")]

    snapshot = truncate_snapshot(
        messages=messages,
        response_content="你" * 1_000,
        max_bytes=100,
    )

    assert snapshot.truncated is True
    assert snapshot.response_content is not None
    assert snapshot.response_content.encode("utf-8").decode("utf-8") == snapshot.response_content
    assert "\ufffd" not in snapshot.response_content
    assert len(snapshot.response_content.encode("utf-8")) <= 100 // 4


def test_truncate_snapshot_truncates_nested_content_part_text() -> None:
    messages = [
        _message(
            "user",
            [{"type": "text", "text": "y" * 1_000}, {"type": "image_url", "image_url": "z"}],
        )
    ]

    snapshot = truncate_snapshot(messages=messages, response_content=None, max_bytes=300)

    assert snapshot.truncated is True
    content = snapshot.messages[0]["content"]
    assert isinstance(content, list)
    text_part = content[0]
    assert isinstance(text_part, dict)
    assert len(str(text_part["text"])) < 1_000
    assert snapshot.messages[0].get("truncated") is True


def test_truncate_snapshot_best_effort_keeps_every_message_and_flags_truncation() -> None:
    messages = [_message("user", "x" * 1_000) for _ in range(10)]

    snapshot = truncate_snapshot(
        messages=messages,
        response_content=None,
        max_bytes=100,
        min_text_chars=10,
    )

    assert snapshot.truncated is True
    assert len(snapshot.messages) == 10
    assert all(len(str(message["content"])) <= 10 for message in snapshot.messages)
    assert all(message.get("truncated") is True for message in snapshot.messages)


def _snapshot_bytes_with_extras(
    messages: Sequence[Mapping[str, object]],
    response: str | None,
    extras: Sequence[object],
) -> int:
    payload: dict[str, object] = {"messages": list(messages), "response": response}
    if extras:
        payload["extras"] = list(extras)
    return len(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def test_truncate_snapshot_counts_extras_in_the_byte_budget() -> None:
    messages = [_message("user", "hello")]
    extras = (
        {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "d" * 2_000,
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        },
    )

    snapshot = truncate_snapshot(
        messages=messages,
        response_content=None,
        max_bytes=600,
        extras=extras,
    )

    assert snapshot.truncated is True
    assert len(snapshot.extras) == 1
    assert (
        _snapshot_bytes_with_extras(snapshot.messages, snapshot.response_content, snapshot.extras)
        <= 600
    )
    tools = snapshot.extras[0]
    assert isinstance(tools, dict)
    function = tools["tools"][0]["function"]
    assert isinstance(function, dict)
    assert len(str(function["description"])) < 2_000


def test_truncate_snapshot_counts_tool_call_arguments_in_the_byte_budget() -> None:
    messages = [_message("user", "hello")]
    tool_calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": "a" * 2_000},
        }
    ]

    snapshot = truncate_snapshot(
        messages=messages,
        response_content=None,
        max_bytes=500,
        extras=(tool_calls,),
    )

    assert snapshot.truncated is True
    assert (
        _snapshot_bytes_with_extras(snapshot.messages, snapshot.response_content, snapshot.extras)
        <= 500
    )
    stored = snapshot.extras[0]
    assert isinstance(stored, list)
    function = stored[0]["function"]
    assert isinstance(function, dict)
    assert len(str(function["arguments"])) < 2_000


def test_truncate_snapshot_does_not_mutate_extras_inputs() -> None:
    extras: tuple[object, ...] = (
        {"tools": [{"function": {"description": "d" * 2_000}}]},
        [{"function": {"arguments": "a" * 2_000}}],
    )
    original = copy.deepcopy(extras)

    snapshot = truncate_snapshot(
        messages=[_message("user", "hello")],
        response_content=None,
        max_bytes=400,
        extras=extras,
    )

    assert snapshot.truncated is True
    assert extras == original
    assert snapshot.extras[0] is not extras[0]
    assert snapshot.extras[1] is not extras[1]


def test_truncate_snapshot_bounds_multibyte_message_text_without_splitting_characters() -> None:
    messages = [_message("user", "你好世界😀" * 200) for _ in range(20)]

    snapshot = truncate_snapshot(
        messages=messages,
        response_content=None,
        max_bytes=2_000,
    )

    assert snapshot.truncated is True
    assert _snapshot_bytes_with_extras(snapshot.messages, None, ()) <= 2_000
    for message in snapshot.messages:
        content = message["content"]
        assert isinstance(content, str)
        assert content.encode("utf-8").decode("utf-8") == content
        assert "\ufffd" not in content


def test_truncate_snapshot_drops_extras_to_empty_structures_at_hard_floor() -> None:
    messages = [_message("user", "x" * 1_000) for _ in range(4)]
    extras: tuple[object, ...] = ({"description": "y" * 1_000}, ["z" * 1_000])

    snapshot = truncate_snapshot(
        messages=messages,
        response_content="r" * 1_000,
        max_bytes=200,
        min_text_chars=10,
        extras=extras,
    )

    assert snapshot.truncated is True
    assert snapshot.response_content is None
    assert snapshot.extras == ({}, [])
    assert len(snapshot.messages) == 4


def test_bound_parameter_changes_keeps_small_values_as_from_to() -> None:
    changes: dict[str, dict[str, object]] = {
        "temperature": {"from": 0.1, "to": 0.7},
        "stop": {"from": None, "to": ["END"]},
    }

    result = bound_parameter_changes(changes=changes, max_value_bytes=256)

    assert result == changes
    assert result is not changes
    assert result["temperature"] is not changes["temperature"]
    assert result["stop"] is not changes["stop"]


def test_bound_parameter_changes_hashes_oversized_values_without_schema_text() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "d" * 1_000,
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        }
    ]
    changes: dict[str, dict[str, object]] = {"tools": {"from": None, "to": tools}}
    canonical = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    result = bound_parameter_changes(changes=changes, max_value_bytes=100)

    entry = result["tools"]
    assert entry == {
        "from_hash": None,
        "to_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "truncated": True,
    }
    assert "from" not in entry
    assert "to" not in entry
    assert "d" * 1_000 not in json.dumps(result)


def test_bound_parameter_changes_hashes_both_oversized_sides() -> None:
    changes: dict[str, dict[str, object]] = {
        "response_format": {
            "from": {"schema": "f" * 500},
            "to": {"schema": "t" * 500},
        }
    }

    result = bound_parameter_changes(changes=changes, max_value_bytes=100)

    entry = result["response_format"]
    assert entry["truncated"] is True
    assert isinstance(entry["from_hash"], str)
    assert isinstance(entry["to_hash"], str)
    assert entry["from_hash"] != entry["to_hash"]
    assert "f" * 500 not in json.dumps(result)
    assert "t" * 500 not in json.dumps(result)


def test_bound_parameter_changes_does_not_mutate_input() -> None:
    changes: dict[str, dict[str, object]] = {
        "tools": {"from": None, "to": [{"function": {"description": "d" * 500}}]},
    }
    original = copy.deepcopy(changes)

    result = bound_parameter_changes(changes=changes, max_value_bytes=50)
    result["tools"]["to_hash"] = "changed"

    assert changes == original


def test_bound_parameter_changes_passes_through_already_bounded_entries() -> None:
    entry: dict[str, object] = {
        "from_hash": "f" * 64,
        "to_hash": "e" * 64,
        "truncated": True,
    }
    changes: dict[str, dict[str, object]] = {"tools": entry}

    result = bound_parameter_changes(changes=changes, max_value_bytes=0)

    assert result["tools"] == entry
    assert "from" not in result["tools"]
    assert "to" not in result["tools"]
