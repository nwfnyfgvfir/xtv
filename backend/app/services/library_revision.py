from __future__ import annotations

import threading

_lock = threading.Lock()
# library_id -> monotonic content revision (LibraryChanged equivalent)
_revisions: dict[int, int] = {}


def get_revision(library_id: int) -> int:
    with _lock:
        return _revisions.get(library_id, 0)


def bump_revision(library_id: int, amount: int = 1) -> int:
    if amount <= 0:
        return get_revision(library_id)
    with _lock:
        cur = _revisions.get(library_id, 0) + amount
        _revisions[library_id] = cur
        return cur


def revisions_snapshot() -> dict[int, int]:
    with _lock:
        return dict(_revisions)
