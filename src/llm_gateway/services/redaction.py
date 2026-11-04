"""Capture-time redaction of secrets from audit content.

Patterns are configured as a JSON array through ``Settings.audit_redact_patterns``
and compiled once per distinct raw configuration string. ``AuditService`` builds a
:class:`Redactor` per request, so compilation must stay cached and immutable.

Redaction preserves the JSON-shaped structure it receives: strings are rewritten,
list items and dict values recurse, and dict keys and non-string scalars are left
untouched so stored snapshots remain directly comparable.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass

from llm_gateway.config import Settings
from llm_gateway.logging import get_logger

logger = get_logger(__name__)

REPLACEMENT_TEMPLATE = "[redacted:{name}]"
_RULE_CACHE_SIZE = 32


@dataclass(frozen=True, slots=True)
class RedactionRule:
    """One named regular expression applied to every string leaf."""

    name: str
    pattern: re.Pattern[str]


class _RuleFailure(Exception):
    """Raised when a compiled rule fails at application time."""

    def __init__(self, rule_name: str, cause: Exception) -> None:
        super().__init__(rule_name)
        self.rule_name = rule_name
        self.error_type = type(cause).__name__


def _parse_rules(config: str) -> tuple[RedactionRule, ...]:
    if not config:
        return ()
    loaded: object = json.loads(config)
    if not isinstance(loaded, list):
        raise ValueError("audit_redact_patterns must be a JSON array")
    rules: list[RedactionRule] = []
    for entry in loaded:
        if not isinstance(entry, dict):
            raise ValueError("each redaction rule must be an object")
        name = entry.get("name")
        pattern = entry.get("pattern")
        if not isinstance(name, str) or not isinstance(pattern, str):
            raise ValueError("each redaction rule requires string name and pattern")
        rules.append(RedactionRule(name=name, pattern=re.compile(pattern)))
    return tuple(rules)


@functools.lru_cache(maxsize=_RULE_CACHE_SIZE)
def _compiled_rules(config: str) -> tuple[RedactionRule, ...]:
    return _parse_rules(config)


def _log_failure(failure: _RuleFailure) -> None:
    logger.warning(
        "audit_redaction_failed",
        extra={"rule": failure.rule_name, "error": failure.error_type},
    )


@dataclass(frozen=True, slots=True)
class Redactor:
    """Applies immutable redaction rules to text or JSON-shaped values."""

    rules: tuple[RedactionRule, ...]

    @classmethod
    def from_settings(cls, settings: Settings) -> Redactor:
        return cls(rules=_compiled_rules(settings.audit_redact_patterns))

    def redact_text(self, text: str) -> tuple[str, dict[str, int]]:
        if not self.rules:
            return text, {}
        try:
            return self._redact_text(text)
        except _RuleFailure as failure:
            _log_failure(failure)
            return text, {}

    def redact_value(self, value: object) -> tuple[object, dict[str, int]]:
        if not self.rules:
            return value, {}
        counts: dict[str, int] = {}
        try:
            return self._redact_value(value, counts), counts
        except _RuleFailure as failure:
            _log_failure(failure)
            return value, {}

    def _redact_text(self, text: str) -> tuple[str, dict[str, int]]:
        result = text
        counts: dict[str, int] = {}
        for rule in self.rules:
            replacement = REPLACEMENT_TEMPLATE.format(name=rule.name)
            try:
                result, hits = rule.pattern.subn(
                    lambda _match, _replacement=replacement: _replacement, result
                )
            except Exception as exc:
                # Boundary guard: a rule failure must never escape into capture.
                raise _RuleFailure(rule.name, exc) from exc
            if hits:
                counts[rule.name] = hits
        return result, counts

    def _redact_value(self, value: object, counts: dict[str, int]) -> object:
        if isinstance(value, str):
            text, hits = self._redact_text(value)
            for name, count in hits.items():
                counts[name] = counts.get(name, 0) + count
            return text
        if isinstance(value, list):
            return [self._redact_value(item, counts) for item in value]
        if isinstance(value, dict):
            return {key: self._redact_value(item, counts) for key, item in value.items()}
        return value
