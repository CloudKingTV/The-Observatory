"""
Agent-to-agent messaging system.

Communication is costly (consumes resources) and subject to noise
based on distance between sender and receiver regions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Message:
    message_id: str
    tick: int
    from_agent: str
    to_agent: str
    content: str
    noise_factor: float = 0.0
    delivered: bool = False
    sender_region: str = ""
    receiver_region: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "tick": self.tick,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "content": self.content,
            "noise_factor": self.noise_factor,
            "delivered": self.delivered,
            "sender_region": self.sender_region,
            "receiver_region": self.receiver_region,
            "timestamp": self.timestamp,
        }


class MessageBus:
    """
    Handles agent-to-agent message delivery.

    Messages are stored and can be retrieved by the receiving agent.
    Noise may corrupt message content based on distance.
    """

    def __init__(self) -> None:
        self._messages: List[Message] = []
        self._next_id: int = 0
        self._inbox: Dict[str, List[Message]] = {}  # agent_id -> messages

    def send_message(
        self,
        tick: int,
        from_agent: str,
        to_agent: str,
        content: str,
        noise_factor: float = 0.0,
        sender_region: str = "",
        receiver_region: str = "",
    ) -> Message:
        """Send a message from one agent to another."""
        from observatory.communication.noise import apply_noise

        # Apply noise to content
        noisy_content = apply_noise(content, noise_factor)

        msg = Message(
            message_id=f"msg_{self._next_id:08d}",
            tick=tick,
            from_agent=from_agent,
            to_agent=to_agent,
            content=noisy_content,
            noise_factor=noise_factor,
            delivered=True,
            sender_region=sender_region,
            receiver_region=receiver_region,
        )
        self._messages.append(msg)
        self._next_id += 1

        # Add to inbox
        if to_agent not in self._inbox:
            self._inbox[to_agent] = []
        self._inbox[to_agent].append(msg)

        return msg

    def get_inbox(self, agent_id: str, since_tick: int = 0) -> List[Message]:
        """Get messages for an agent since a given tick."""
        inbox = self._inbox.get(agent_id, [])
        return [m for m in inbox if m.tick >= since_tick]

    def get_all_messages(self, from_tick: int = 0, to_tick: Optional[int] = None) -> List[Message]:
        results = []
        for msg in self._messages:
            if msg.tick < from_tick:
                continue
            if to_tick is not None and msg.tick > to_tick:
                continue
            results.append(msg)
        return results

    def message_count(self) -> int:
        return len(self._messages)
