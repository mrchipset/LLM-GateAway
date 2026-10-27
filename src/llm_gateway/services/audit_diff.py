"""Pure, dependency-free helpers for deterministic request-audit turn diffs.

This module intentionally performs no I/O and reads no clock. Every function is a
deterministic transform over JSON-shaped values so that audit records can be
compared byte-for-byte across processes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

CANONICAL_FIELDS = ("role", "content", "name", "tool_calls", "tool_call_id")

_PARAMETER_FIELDS = (
    "model",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "n",
    "seed",
    "user",
    "response_format",
    "tools",
    "tool_choice",
    "stream_options",
)

_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "cached_tokens", "total_tokens")

ChangeType = Literal["new_session", "continuation", "regeneration", "edit", "truncation"]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_message(message: Mapping[str, object]) -> str:
    """Serialize a message using only the canonical fields and stable ordering."""

    payload = {field: message[field] for field in CANONICAL_FIELDS if field in message}
    return _canonical_json(payload)


def message_hash(message: Mapping[str, object]) -> str:
    return _sha256_hex(canonical_message(message))


def message_hashes(messages: Sequence[Mapping[str, object]]) -> list[str]:
    return [message_hash(message) for message in messages]


def first_user_message_index(messages: Sequence[Mapping[str, object]]) -> int | None:
    for index, message in enumerate(messages):
        if message.get("role") == "user":
            return index
    return None


def common_prefix_length(left: Sequence[str], right: Sequence[str]) -> int:
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return index
    return limit


def canonical_text(text: str | None) -> str:
    """Normalize free text for hashing; missing text canonicalizes to empty."""

    return "" if text is None else text


def text_hash(text: str | None) -> str | None:
    if text is None:
        return None
    return _sha256_hex(canonical_text(text))


@dataclass(frozen=True, slots=True)
class PrefixCandidate:
    request_id: str
    session_id: str
    turn_index: int
    message_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrefixMatch:
    candidate: PrefixCandidate | None
    common_prefix: int
    method: Literal["prefix", "new"]


def match_prefix_candidate(
    *,
    current_messages: Sequence[Mapping[str, object]],
    current_hashes: Sequence[str],
    candidates: Sequence[PrefixCandidate],
) -> PrefixMatch:
    """Pick the newest candidate whose shared history extends past the first user turn.

    Candidates are expected to be supplied newest-first. Ties keep the earliest
    (newest) candidate in that order.
    """

    first_user = first_user_message_index(current_messages)
    if first_user is None:
        return PrefixMatch(candidate=None, common_prefix=0, method="new")

    best: PrefixCandidate | None = None
    best_prefix = 0
    for candidate in candidates:
        prefix = common_prefix_length(current_hashes, candidate.message_hashes)
        if prefix < 1 or prefix <= first_user:
            continue
        if prefix > best_prefix:
            best = candidate
            best_prefix = prefix

    if best is None:
        return PrefixMatch(candidate=None, common_prefix=0, method="new")
    return PrefixMatch(candidate=best, common_prefix=best_prefix, method="prefix")


@dataclass(frozen=True, slots=True)
class ResponseSummary:
    content_hash: str | None
    finish_reason: str | None
    tool_call_count: int
    tool_call_names: tuple[str, ...]


def _tool_call_name(tool_call: Mapping[str, object]) -> str | None:
    function = tool_call.get("function")
    if isinstance(function, Mapping):
        name = function.get("name")
        if isinstance(name, str):
            return name
    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    return None


def summarize_response(
    *,
    content: str | None,
    tool_calls: Sequence[Mapping[str, object]] | None,
    finish_reason: str | None,
) -> ResponseSummary:
    names: list[str] = []
    if tool_calls is not None:
        for tool_call in tool_calls:
            name = _tool_call_name(tool_call)
            if name is not None:
                names.append(name)
    return ResponseSummary(
        content_hash=text_hash(content),
        finish_reason=finish_reason,
        tool_call_count=0 if tool_calls is None else len(tool_calls),
        tool_call_names=tuple(names),
    )


def classify_change(
    *,
    current_hashes: Sequence[str],
    parent_hashes: Sequence[str] | None,
) -> ChangeType:
    if parent_hashes is None:
        return "new_session"
    if list(current_hashes) == list(parent_hashes):
        return "regeneration"
    if common_prefix_length(current_hashes, parent_hashes) == len(parent_hashes):
        return "continuation"
    if common_prefix_length(current_hashes, parent_hashes) == len(current_hashes):
        return "truncation"
    return "edit"


def _content_text(content: object) -> str:
    """Flatten message content (including content-part lists) to display text."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(_canonical_json(part))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def message_preview(message: Mapping[str, object], limit: int) -> str:
    text = _content_text(message.get("content"))
    safe_limit = max(0, limit)
    return text[:safe_limit]


def _message_role(message: Mapping[str, object]) -> str:
    role = message.get("role")
    return role if isinstance(role, str) else ""


def _added_entry(
    message: Mapping[str, object],
    *,
    index: int,
    digest: str,
    preview_chars: int,
) -> dict[str, object]:
    return {
        "index": index,
        "role": _message_role(message),
        "hash": digest,
        "preview": message_preview(message, preview_chars),
    }


def _modified_entry(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    index: int,
    before_hash: str,
    after_hash: str,
    preview_chars: int,
) -> dict[str, object]:
    return {
        "index": index,
        "role": _message_role(after),
        "before_hash": before_hash,
        "after_hash": after_hash,
        "before_preview": message_preview(before, preview_chars),
        "after_preview": message_preview(after, preview_chars),
    }


def _parameter_changes(
    current_params: Mapping[str, object],
    parent_params: Mapping[str, object] | None,
) -> dict[str, dict[str, object]]:
    previous = parent_params if parent_params is not None else {}
    changes: dict[str, dict[str, object]] = {}
    for field in _PARAMETER_FIELDS:
        old = previous.get(field)
        new = current_params.get(field)
        if _canonical_json(old) == _canonical_json(new):
            continue
        changes[field] = {"from": old, "to": new}
    return changes


def bound_parameter_changes(
    *,
    changes: Mapping[str, Mapping[str, object]],
    max_value_bytes: int,
) -> dict[str, dict[str, object]]:
    """Replace oversized parameter values with deterministic hashes.

    Small values keep their ``from``/``to`` payload; a value larger than
    ``max_value_bytes`` cannot be exposed without bypassing the row budget.
    Entries that are already bounded (``from_hash``/``to_hash``) pass through
    unchanged so bounded diffs stay idempotent.
    """

    bounded: dict[str, dict[str, object]] = {}
    for field, change in changes.items():
        if "from_hash" in change or "to_hash" in change:
            bounded[field] = dict(change)
            continue
        from_value = change.get("from")
        to_value = change.get("to")
        from_json = _canonical_json(from_value)
        to_json = _canonical_json(to_value)
        if (
            len(from_json.encode("utf-8")) > max_value_bytes
            or len(to_json.encode("utf-8")) > max_value_bytes
        ):
            bounded[field] = {
                "from_hash": None if from_value is None else _sha256_hex(from_json),
                "to_hash": None if to_value is None else _sha256_hex(to_json),
                "truncated": True,
            }
        else:
            bounded[field] = {"from": from_value, "to": to_value}
    return bounded


def _usage_delta(
    current_usage: Mapping[str, int] | None,
    parent_usage: Mapping[str, int] | None,
) -> dict[str, int]:
    if current_usage is None or parent_usage is None:
        return {}
    return {
        field: _int_or_zero(current_usage.get(field)) - _int_or_zero(parent_usage.get(field))
        for field in _USAGE_FIELDS
    }


def _int_or_zero(value: int | None) -> int:
    return 0 if value is None else value


def _response_change(
    current_response: ResponseSummary | None,
    parent_response: ResponseSummary | None,
) -> dict[str, object]:
    if parent_response is None:
        return {
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

    if current_response is None:
        current_content_hash = None
        current_finish_reason = None
        current_tool_calls = 0
        current_tool_names: list[str] = []
    else:
        current_content_hash = current_response.content_hash
        current_finish_reason = current_response.finish_reason
        current_tool_calls = current_response.tool_call_count
        current_tool_names = list(current_response.tool_call_names)

    return {
        "content_changed": current_content_hash != parent_response.content_hash,
        "previous_content_hash": parent_response.content_hash,
        "content_hash": current_content_hash,
        "finish_reason_changed": current_finish_reason != parent_response.finish_reason,
        "previous_finish_reason": parent_response.finish_reason,
        "finish_reason": current_finish_reason,
        "tool_calls_added": max(0, current_tool_calls - parent_response.tool_call_count),
        "tool_calls_removed": max(0, parent_response.tool_call_count - current_tool_calls),
        "tool_call_names": current_tool_names,
    }


@dataclass(frozen=True, slots=True)
class TurnDiff:
    change_type: ChangeType
    common_prefix: int
    added_messages: list[dict[str, object]]
    modified_messages: list[dict[str, object]]
    removed_messages: list[dict[str, object]]
    parameter_changes: dict[str, dict[str, object]]
    usage_delta: dict[str, int]
    response_change: dict[str, object]


def build_turn_diff(
    *,
    change_type: ChangeType,
    current_messages: Sequence[Mapping[str, object]],
    current_hashes: Sequence[str],
    parent_messages: Sequence[Mapping[str, object]] | None,
    parent_hashes: Sequence[str] | None,
    current_params: Mapping[str, object],
    parent_params: Mapping[str, object] | None,
    current_usage: Mapping[str, int] | None,
    parent_usage: Mapping[str, int] | None,
    current_response: ResponseSummary | None,
    parent_response: ResponseSummary | None,
    preview_chars: int = 160,
) -> TurnDiff:
    previous_messages = list(parent_messages) if parent_messages is not None else []
    previous_hashes = list(parent_hashes) if parent_hashes is not None else []

    if change_type == "new_session":
        common_prefix = 0
    elif change_type == "regeneration":
        common_prefix = len(current_hashes)
    else:
        common_prefix = common_prefix_length(current_hashes, previous_hashes)

    added: list[dict[str, object]] = []
    modified: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []

    if change_type == "new_session":
        added = [
            _added_entry(
                message,
                index=index,
                digest=current_hashes[index],
                preview_chars=preview_chars,
            )
            for index, message in enumerate(current_messages)
        ]
    elif change_type == "continuation":
        added = [
            _added_entry(
                message,
                index=index,
                digest=current_hashes[index],
                preview_chars=preview_chars,
            )
            for index, message in enumerate(current_messages)
            if index >= common_prefix
        ]
    elif change_type == "truncation":
        removed = [
            _added_entry(
                message,
                index=index,
                digest=previous_hashes[index],
                preview_chars=preview_chars,
            )
            for index, message in enumerate(previous_messages)
            if index >= common_prefix
        ]
    elif change_type == "edit":
        if common_prefix < len(previous_messages) and common_prefix < len(current_messages):
            modified.append(
                _modified_entry(
                    previous_messages[common_prefix],
                    current_messages[common_prefix],
                    index=common_prefix,
                    before_hash=previous_hashes[common_prefix],
                    after_hash=current_hashes[common_prefix],
                    preview_chars=preview_chars,
                )
            )
        added = [
            _added_entry(
                message,
                index=index,
                digest=current_hashes[index],
                preview_chars=preview_chars,
            )
            for index, message in enumerate(current_messages)
            if index > common_prefix
        ]
        removed = [
            _added_entry(
                message,
                index=index,
                digest=previous_hashes[index],
                preview_chars=preview_chars,
            )
            for index, message in enumerate(previous_messages)
            if index > common_prefix
        ]

    return TurnDiff(
        change_type=change_type,
        common_prefix=common_prefix,
        added_messages=added,
        modified_messages=modified,
        removed_messages=removed,
        parameter_changes=_parameter_changes(current_params, parent_params),
        usage_delta=_usage_delta(current_usage, parent_usage),
        response_change=_response_change(current_response, parent_response),
    )


@dataclass(frozen=True, slots=True)
class TruncatedSnapshot:
    messages: list[dict[str, object]]
    response_content: str | None
    truncated: bool
    extras: tuple[object, ...] = ()


def _count_string_leaves(value: object) -> int:
    if isinstance(value, str):
        return 1
    if isinstance(value, Mapping):
        return sum(_count_string_leaves(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_string_leaves(item) for item in value)
    return 0


def _count_message_string_leaves(message: Mapping[str, object]) -> int:
    # ``role`` is structural and must never be shortened.
    return sum(_count_string_leaves(value) for key, value in message.items() if key != "role")


def _truncate_string_leaves(value: object, max_bytes: int) -> tuple[object, bool]:
    """Shrink every string leaf with UTF-8-safe byte slicing."""

    if isinstance(value, str):
        shortened = _truncate_utf8_bytes(value, max_bytes)
        return shortened, shortened != value
    if isinstance(value, Mapping):
        result: dict[object, object] = {}
        changed = False
        for key, item in value.items():
            converted, item_changed = _truncate_string_leaves(item, max_bytes)
            result[key] = converted
            changed = changed or item_changed
        return result, changed
    if isinstance(value, list):
        items: list[object] = []
        changed = False
        for item in value:
            converted, item_changed = _truncate_string_leaves(item, max_bytes)
            items.append(converted)
            changed = changed or item_changed
        return items, changed
    return value, False


def _snapshot_size(
    messages: Sequence[Mapping[str, object]],
    response: str | None,
    extras: Sequence[object] = (),
) -> int:
    payload: dict[str, object] = {"messages": list(messages), "response": response}
    if extras:
        payload["extras"] = list(extras)
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    safe_limit = max(0, max_bytes)
    encoded = text.encode("utf-8")
    if len(encoded) <= safe_limit:
        return text
    return encoded[:safe_limit].decode("utf-8", errors="ignore")


def _shrink_messages(
    messages: list[dict[str, object]],
    max_bytes: int,
) -> None:
    for message in messages:
        changed = False
        for key, value in message.items():
            if key in ("role", "truncated"):
                continue
            converted, item_changed = _truncate_string_leaves(value, max_bytes)
            if item_changed:
                message[key] = converted
                changed = True
        if changed:
            message["truncated"] = True


def _shrink_extras(extras: list[object], max_bytes: int) -> None:
    for index, value in enumerate(extras):
        converted, _changed = _truncate_string_leaves(value, max_bytes)
        extras[index] = converted


def _empty_extra(value: object) -> object:
    if isinstance(value, list):
        return []
    if isinstance(value, Mapping):
        return {}
    return None


def truncate_snapshot(
    *,
    messages: Sequence[Mapping[str, object]],
    response_content: str | None,
    max_bytes: int,
    min_text_chars: int = 64,
    extras: Sequence[object] = (),
) -> TruncatedSnapshot:
    """Bound a stored snapshot while making every truncation observable.

    ``extras`` covers JSON payloads stored next to the messages (request params,
    response tool calls). They share the byte budget and are truncated by the same
    UTF-8-safe rules. Messages are never dropped; extras fall back to empty
    structures at the hard floor.
    """

    copied: list[dict[str, object]] = [copy.deepcopy(dict(message)) for message in messages]
    copied_extras: list[object] = [copy.deepcopy(value) for value in extras]
    response = response_content

    if _snapshot_size(copied, response, copied_extras) <= max_bytes:
        return TruncatedSnapshot(
            messages=copied,
            response_content=response,
            truncated=False,
            extras=tuple(copied_extras),
        )

    # Step 1: cap the response to a quarter of the byte budget.
    if response is not None:
        response = _truncate_utf8_bytes(response, max_bytes // 4)
        if _snapshot_size(copied, response, copied_extras) <= max_bytes:
            return TruncatedSnapshot(
                messages=copied,
                response_content=response,
                truncated=True,
                extras=tuple(copied_extras),
            )

    # Step 2: cap every string leaf across messages and extras.
    text_fields = sum(_count_message_string_leaves(message) for message in copied)
    text_fields += sum(_count_string_leaves(value) for value in copied_extras)
    per_text = max(1, (max_bytes // 2) // max(1, text_fields))
    _shrink_messages(copied, per_text)
    _shrink_extras(copied_extras, per_text)
    if _snapshot_size(copied, response, copied_extras) <= max_bytes:
        return TruncatedSnapshot(
            messages=copied,
            response_content=response,
            truncated=True,
            extras=tuple(copied_extras),
        )

    # Step 3: hard byte floor. Never drops messages; extras degrade to empties.
    _shrink_messages(copied, min_text_chars)
    _shrink_extras(copied_extras, min_text_chars)
    if response is not None:
        response = _truncate_utf8_bytes(response, min_text_chars)
    if _snapshot_size(copied, response, copied_extras) > max_bytes:
        copied_extras = [_empty_extra(value) for value in copied_extras]
        response = None
    return TruncatedSnapshot(
        messages=copied,
        response_content=response,
        truncated=True,
        extras=tuple(copied_extras),
    )
