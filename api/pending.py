"""Open questions, kept in memory until the runner answers (Phase 3, step 5; decision 029).

A parse that ends in a question is kept here under its parse_id: the extraction, the request's context, what earlier
answers settled and the question's answer map. An answer within PENDING_TTL_S resumes it with no second Claude call.
After that, or after a server restart, the answer gets an `expired` error and the app resends the original request
(Jared, 2026-11-08). Nothing here is written to disk or logged: the context holds the runner's location.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

PENDING_TTL_S = 15 * 60
MAX_PENDING = 200  # one runner today; the oldest go first past this


@dataclass
class Pending:
    parse_id: str
    question_id: str
    ext: dict
    request: dict  # the original request (text, client, profile, recent_routes)
    answers: dict
    answer_map: dict
    created: float = field(default=0.0)


class PendingStore:
    def __init__(self, ttl_s: float = PENDING_TTL_S, clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.clock = ttl_s, clock
        self._items: dict[str, Pending] = {}
        self._lock = threading.Lock()

    def put(self, item: Pending) -> None:
        with self._lock:
            self._expire()
            item.created = self.clock()
            self._items[item.parse_id] = item
            while len(self._items) > MAX_PENDING:
                self._items.pop(next(iter(self._items)))

    def take(self, parse_id: str) -> Pending | None:
        """The pending parse, removed (an answer is used once), or None when it is unknown or expired."""
        with self._lock:
            self._expire()
            return self._items.pop(parse_id, None)

    def __len__(self) -> int:
        with self._lock:
            self._expire()
            return len(self._items)

    def _expire(self) -> None:
        cutoff = self.clock() - self.ttl_s
        for key in [k for k, v in self._items.items() if v.created < cutoff]:
            del self._items[key]
