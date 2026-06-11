from __future__ import annotations

from typing import List

from declaw.sandbox.filesystem.models import FilesystemEvent


class AsyncWatchHandle:
    """Async handle for watching filesystem events."""

    def __init__(self) -> None:
        self._events: List[FilesystemEvent] = []
        self._stopped = False

    async def stop(self) -> None:
        self._stopped = True

    def _push_event(self, event: FilesystemEvent) -> None:
        if not self._stopped:
            self._events.append(event)

    async def get_new_events(self) -> List[FilesystemEvent]:
        events = list(self._events)
        self._events.clear()
        return events
