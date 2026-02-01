"""
World state management.

Maintains the canonical world state. All state is server-authoritative.
Persistence via JSON snapshots to survive restarts.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from observatory.world.regions import RegionManager
from observatory.world.resources import ResourcePool


def _get_state_file() -> str:
    return os.environ.get("OBSERVATORY_STATE_FILE", "world_state.json")


@dataclass
class AgentState:
    agent_id: str
    display_name: str
    public_key: str
    region: str
    resources: ResourcePool
    status: str  # "unclaimed", "claimed", "dead", "forked"
    owner_identity: Optional[str] = None  # x_handle or other proof
    claim_token: Optional[str] = None
    claim_token_expires: Optional[float] = None
    alliances: List[str] = field(default_factory=list)
    created_at_tick: int = 0
    died_at_tick: Optional[int] = None
    parent_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_alive(self) -> bool:
        return self.status in ("unclaimed", "claimed")

    def is_claimed(self) -> bool:
        return self.status == "claimed"

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "public_key": self.public_key,
            "region": self.region,
            "resources": self.resources.to_dict(),
            "resource_caps": {rt.value: cap for rt, cap in self.resources.caps.items()},
            "status": self.status,
            "owner_identity": self.owner_identity,
            "claim_token": self.claim_token,
            "claim_token_expires": self.claim_token_expires,
            "alliances": self.alliances,
            "created_at_tick": self.created_at_tick,
            "died_at_tick": self.died_at_tick,
            "parent_agent": self.parent_agent,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentState":
        resources = ResourcePool.from_dict(
            data.get("resources", {}),
            data.get("resource_caps"),
        )
        return cls(
            agent_id=data["agent_id"],
            display_name=data.get("display_name", ""),
            public_key=data.get("public_key", ""),
            region=data.get("region", "nexus"),
            resources=resources,
            status=data.get("status", "unclaimed"),
            owner_identity=data.get("owner_identity"),
            claim_token=data.get("claim_token"),
            claim_token_expires=data.get("claim_token_expires"),
            alliances=data.get("alliances", []),
            created_at_tick=data.get("created_at_tick", 0),
            died_at_tick=data.get("died_at_tick"),
            parent_agent=data.get("parent_agent"),
            metadata=data.get("metadata", {}),
        )

    def public_dict(self) -> dict:
        """Return observer-safe view (no secrets)."""
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "region": self.region,
            "resources": self.resources.to_dict(),
            "status": self.status,
            "owner_identity": self.owner_identity,
            "alliances": self.alliances,
            "created_at_tick": self.created_at_tick,
            "died_at_tick": self.died_at_tick,
            "parent_agent": self.parent_agent,
        }


class WorldState:
    """Canonical, thread-safe world state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.tick: int = 0
        self.agents: Dict[str, AgentState] = {}
        self.region_manager: RegionManager = RegionManager()
        self.pending_trades: List[Dict[str, Any]] = []
        self.alliance_proposals: List[Dict[str, Any]] = []

    def initialize(self) -> None:
        """Initialize with default regions."""
        with self._lock:
            self.region_manager.initialize_defaults()

    def add_agent(self, agent: AgentState) -> None:
        with self._lock:
            self.agents[agent.agent_id] = agent
            region = self.region_manager.get(agent.region)
            if region:
                region.add_agent(agent.agent_id)

    def get_agent(self, agent_id: str) -> Optional[AgentState]:
        with self._lock:
            return self.agents.get(agent_id)

    def remove_agent(self, agent_id: str) -> None:
        with self._lock:
            agent = self.agents.get(agent_id)
            if agent:
                region = self.region_manager.get(agent.region)
                if region:
                    region.remove_agent(agent_id)

    def get_all_agents_summary(self) -> Dict[str, dict]:
        """Return minimal agent info dict for rules engine."""
        with self._lock:
            return {
                aid: {"region": a.region, "status": a.status}
                for aid, a in self.agents.items()
            }

    def advance_tick(self) -> int:
        with self._lock:
            self.tick += 1
            return self.tick

    def save(self, filepath: Optional[str] = None) -> None:
        """Persist world state to JSON."""
        filepath = filepath or _get_state_file()
        with self._lock:
            data = {
                "tick": self.tick,
                "agents": {aid: a.to_dict() for aid, a in self.agents.items()},
                "regions": self.region_manager.to_dict(),
                "pending_trades": self.pending_trades,
                "alliance_proposals": self.alliance_proposals,
            }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def load(self, filepath: Optional[str] = None) -> bool:
        """Load world state from JSON. Returns True if loaded successfully."""
        filepath = filepath or _get_state_file()
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            with self._lock:
                self.tick = data.get("tick", 0)
                self.agents = {
                    aid: AgentState.from_dict(adict)
                    for aid, adict in data.get("agents", {}).items()
                }
                regions_data = data.get("regions", {})
                if regions_data:
                    self.region_manager = RegionManager.from_dict(regions_data)
                    # Re-populate region agent lists from agent state
                    for aid, agent in self.agents.items():
                        if agent.is_alive():
                            region = self.region_manager.get(agent.region)
                            if region and aid not in region.current_agents:
                                region.current_agents.append(aid)
                else:
                    self.region_manager.initialize_defaults()
                self.pending_trades = data.get("pending_trades", [])
                self.alliance_proposals = data.get("alliance_proposals", [])
            return True
        except (json.JSONDecodeError, KeyError):
            return False

    def snapshot(self) -> dict:
        """Return full state as dict for observer API."""
        with self._lock:
            return {
                "tick": self.tick,
                "agents": {aid: a.public_dict() for aid, a in self.agents.items()},
                "regions": self.region_manager.to_dict(),
                "pending_trades_count": len(self.pending_trades),
                "alliance_proposals_count": len(self.alliance_proposals),
            }
