"""Kill switch — master prompt §11.

A global emergency stop. When engaged:
1. Stop current automation
2. Cancel queued actions
3. Release mouse/keyboard control
4. Stop active workflows
5. Record interruption
6. Return to safe state
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from ..engine.event_bus import event_bus


class KillSwitch:
    def __init__(self) -> None:
        self.engaged: bool = False
        self.engaged_at: Optional[datetime] = None
        self.reason: Optional[str] = None
        self._cancel_event: Optional[asyncio.Event] = None

    def engage(self, reason: str = "manual") -> None:
        self.engaged = True
        self.engaged_at = datetime.now(timezone.utc)
        self.reason = reason
        if self._cancel_event is not None:
            self._cancel_event.set()
        event_bus.publish("EMERGENCY_STOP", {"reason": reason, "at": self.engaged_at.isoformat()})

    def reset(self) -> None:
        self.engaged = False
        self.engaged_at = None
        self.reason = None

    def get_cancel_event(self) -> asyncio.Event:
        """Returns an asyncio.Event that gets set when the kill switch engages."""
        ev = asyncio.Event()
        if self.engaged:
            ev.set()
        self._cancel_event = ev
        return ev


kill_switch = KillSwitch()
