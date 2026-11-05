"""Sampling for ``last_used_at``.

Every authenticated request used to write the key row. The timestamp is
informational, so it is refreshed at most once per interval per key instead of on
every call. The state is process-local: with several workers the effective
interval is divided by the worker count, which is acceptable for a display
field and keeps the hot path free of another shared dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

_PRUNE_AT = 10_000


@dataclass(slots=True)
class LastUsedSampler:
    interval_seconds: float = 60.0
    _last: dict[UUID, datetime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be >= 0")

    def should_touch(self, key_id: UUID, now: datetime) -> bool:
        """Return True when the caller should persist ``last_used_at``."""
        if self.interval_seconds == 0:
            return True
        previous = self._last.get(key_id)
        if previous is not None and (now - previous).total_seconds() < self.interval_seconds:
            return False
        if len(self._last) >= _PRUNE_AT:
            self._last.clear()
        self._last[key_id] = now
        return True
