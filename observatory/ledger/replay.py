"""
Event replay system.

Reconstructs world state at any historical tick by replaying
events from the append-only ledger.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from observatory.ledger.events import Event, EventLedger
from observatory.world.regions import RegionManager
from observatory.world.resources import ResourcePool
from observatory.world.state import AgentState, WorldState


class ReplayEngine:
    """
    Replays events to reconstruct world state at any point in time.

    This enables observer "rewind" functionality — humans can view
    the world at any historical tick.
    """

    def __init__(self, ledger: EventLedger) -> None:
        self.ledger = ledger

    def reconstruct_at_tick(self, target_tick: int) -> Dict[str, Any]:
        """
        Reconstruct a snapshot of the world at a given tick.

        Returns a dict representing the world state at that tick,
        built from replaying all events up to and including target_tick.
        """
        events = self.ledger.get_events(from_tick=0, to_tick=target_tick, limit=1_000_000)

        # Build state from events
        agents: Dict[str, Dict[str, Any]] = {}
        regions = RegionManager()
        regions.initialize_defaults()

        for event in events:
            self._apply_event(event, agents, regions)

        return {
            "tick": target_tick,
            "agents": agents,
            "regions": regions.to_dict(),
            "total_events": len(events),
        }

    def _apply_event(
        self,
        event: Event,
        agents: Dict[str, Dict[str, Any]],
        regions: RegionManager,
    ) -> None:
        """Apply a single event to the reconstruction state."""
        if not event.success:
            return

        agent_id = event.agent_id
        details = event.details

        if event.action_type == "tick":
            # Tick heartbeat — no state change needed
            return

        if event.action_type == "register":
            agents[agent_id] = {
                "agent_id": agent_id,
                "status": "unclaimed",
                "region": details.get("spawn_region", "nexus"),
                "resources": details.get("initial_resources", {}),
                "alliances": [],
                "created_at_tick": event.tick,
            }
            return

        if event.action_type == "claim":
            if agent_id in agents:
                agents[agent_id]["status"] = "claimed"
                agents[agent_id]["owner_identity"] = details.get("owner_identity")
            return

        if event.action_type == "death":
            if agent_id in agents:
                agents[agent_id]["status"] = "dead"
                agents[agent_id]["died_at_tick"] = event.tick
            return

        if event.action_type == "move":
            if agent_id in agents:
                agents[agent_id]["region"] = details.get("to_region", agents[agent_id].get("region"))
            return

        if event.action_type == "fork":
            child_name = details.get("child_name")
            if child_name:
                agents[child_name] = {
                    "agent_id": child_name,
                    "status": agents.get(agent_id, {}).get("status", "unclaimed"),
                    "region": details.get("spawn_region", "nexus"),
                    "resources": {},
                    "alliances": [],
                    "parent_agent": agent_id,
                    "created_at_tick": event.tick,
                }
            return

        if event.action_type == "merge":
            absorbed = details.get("absorbed_agent")
            if absorbed and absorbed in agents:
                agents[absorbed]["status"] = "dead"
                agents[absorbed]["died_at_tick"] = event.tick
            return

        if event.action_type == "attack":
            # Attack effects are reflected in subsequent death events
            return

        if event.action_type == "ally":
            target = details.get("target_agent")
            if agent_id in agents and target:
                alliances = agents[agent_id].get("alliances", [])
                if target not in alliances:
                    alliances.append(target)
                agents[agent_id]["alliances"] = alliances
            return

    def get_timeline(
        self,
        agent_id: str,
        from_tick: int = 0,
        to_tick: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get the event timeline for a specific agent."""
        events = self.ledger.get_events(
            from_tick=from_tick,
            to_tick=to_tick,
            agent_id=agent_id,
            limit=10000,
        )
        return [e.to_dict() for e in events]

    def get_world_timeline(
        self,
        from_tick: int = 0,
        to_tick: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get the global event timeline."""
        events = self.ledger.get_events(
            from_tick=from_tick,
            to_tick=to_tick,
            limit=limit,
        )
        return [e.to_dict() for e in events]
