"""
Append-only event ledger.

Every validated action creates an immutable event.
No deletions. No edits. History is permanent.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _get_ledger_file() -> str:
    return os.environ.get("OBSERVATORY_LEDGER_FILE", "event_ledger.jsonl")


@dataclass
class Event:
    event_id: int
    tick: int
    action_type: str
    agent_id: str
    success: bool
    details: Dict[str, Any]
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "tick": self.tick,
            "action_type": self.action_type,
            "agent_id": self.agent_id,
            "success": self.success,
            "details": self.details,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class EventLedger:
    """
    Append-only event ledger.

    Events are stored both in memory and persisted to a JSONL file.
    Monotonic IDs guarantee ordering.
    No deletions. No edits.
    """

    def __init__(self, filepath: Optional[str] = None) -> None:
        self._filepath = filepath or _get_ledger_file()
        self._events: List[Event] = []
        self._next_id: int = 0
        self._lock = threading.Lock()
        self._load_existing()

    def _load_existing(self) -> None:
        """Load existing events from the ledger file."""
        if not os.path.exists(self._filepath):
            return
        try:
            with open(self._filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    event = Event(
                        event_id=data["event_id"],
                        tick=data["tick"],
                        action_type=data["action_type"],
                        agent_id=data["agent_id"],
                        success=data["success"],
                        details=data.get("details", {}),
                        error=data.get("error"),
                        timestamp=data.get("timestamp", 0),
                    )
                    self._events.append(event)
                    self._next_id = max(self._next_id, event.event_id + 1)
        except (json.JSONDecodeError, KeyError, IOError):
            pass  # Start fresh if ledger is corrupted

    def append(self, event_data: dict) -> Event:
        """Append a new event. This is the ONLY write operation."""
        with self._lock:
            event = Event(
                event_id=self._next_id,
                tick=event_data.get("tick", 0),
                action_type=event_data.get("action_type", "unknown"),
                agent_id=event_data.get("agent_id", "unknown"),
                success=event_data.get("success", False),
                details=event_data.get("details", {}),
                error=event_data.get("error"),
            )
            self._events.append(event)
            self._next_id += 1

            # Persist to file (append-only)
            try:
                with open(self._filepath, "a") as f:
                    f.write(json.dumps(event.to_dict()) + "\n")
            except IOError:
                pass  # In-memory copy still valid

            return event

    def get_events(
        self,
        from_tick: int = 0,
        to_tick: Optional[int] = None,
        action_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Event]:
        """Query events with filters."""
        results = []
        for event in self._events:
            if event.tick < from_tick:
                continue
            if to_tick is not None and event.tick > to_tick:
                continue
            if action_type and event.action_type != action_type:
                continue
            if agent_id and event.agent_id != agent_id:
                continue
            results.append(event)
            if len(results) >= limit:
                break
        return results

    def get_event_by_id(self, event_id: int) -> Optional[Event]:
        with self._lock:
            if 0 <= event_id < len(self._events):
                return self._events[event_id]
        return None

    def count(self) -> int:
        return len(self._events)

    def latest_tick(self) -> int:
        if not self._events:
            return 0
        return self._events[-1].tick

    def events_at_tick(self, tick: int) -> List[Event]:
        return [e for e in self._events if e.tick == tick]
