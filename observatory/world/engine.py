"""
World engine — the core tick loop.

Discrete tick loop that:
1. Collects queued actions
2. Resolves them deterministically via rules engine
3. Applies resource regeneration and danger
4. Persists state + appends to event ledger
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from observatory.world.rules import ActionResult, RulesEngine
from observatory.world.state import AgentState, WorldState
from observatory.world.resources import ResourcePool

logger = logging.getLogger("observatory.engine")


@dataclass
class QueuedAction:
    agent_id: str
    action_type: str
    params: Dict[str, Any]
    submitted_at_tick: int
    valid_for_ticks: int = 1  # how many ticks this intent remains valid


class WorldEngine:
    """
    The world engine runs a discrete tick loop.
    Actions are queued between ticks and resolved deterministically each tick.
    """

    def __init__(
        self,
        world_state: WorldState,
        tick_duration: float = 5.0,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.world_state = world_state
        self.tick_duration = tick_duration
        self.rules_engine = RulesEngine(world_state.region_manager)
        self._action_queue: Deque[QueuedAction] = deque()
        self._queue_lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_event = on_event  # callback for appending to event ledger

    def enqueue_action(self, action: QueuedAction) -> None:
        with self._queue_lock:
            self._action_queue.append(action)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()
        logger.info("World engine started. Tick duration: %.1fs", self.tick_duration)

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("World engine stopped.")

    def _tick_loop(self) -> None:
        while self._running:
            start = time.monotonic()
            try:
                self._process_tick()
            except Exception:
                logger.exception("Error processing tick %d", self.world_state.tick)
            elapsed = time.monotonic() - start
            sleep_time = max(0, self.tick_duration - elapsed)
            # Use event-based sleep for clean shutdown
            self._stop_event.wait(timeout=sleep_time)

    def _process_tick(self) -> None:
        tick = self.world_state.advance_tick()
        logger.debug("Processing tick %d", tick)

        # 1. Drain action queue
        with self._queue_lock:
            actions = list(self._action_queue)
            self._action_queue.clear()

        # Filter expired actions
        valid_actions = [
            a for a in actions
            if (tick - a.submitted_at_tick) <= a.valid_for_ticks
        ]

        all_agents_summary = self.world_state.get_all_agents_summary()

        # 2. Resolve each action deterministically
        results: List[ActionResult] = []
        for action in valid_actions:
            agent = self.world_state.get_agent(action.agent_id)
            if not agent or not agent.is_alive():
                continue

            # Unclaimed agents are heavily rate-limited (only observe allowed)
            if agent.status == "unclaimed" and action.action_type != "observe":
                results.append(ActionResult(
                    success=False,
                    action_type=action.action_type,
                    agent_id=action.agent_id,
                    details={},
                    tick=tick,
                    error="Agent is unclaimed. Only observe actions are allowed.",
                ))
                continue

            result = self.rules_engine.validate_and_resolve(
                action_type=action.action_type,
                agent_id=action.agent_id,
                agent_resources=agent.resources,
                agent_region=agent.region,
                params=action.params,
                tick=tick,
                all_agents=all_agents_summary,
            )
            results.append(result)

            # Apply side effects for successful actions
            if result.success:
                self._apply_side_effects(result, agent)

        # 3. Apply per-agent tick effects (regen, danger)
        for agent_id, agent in list(self.world_state.agents.items()):
            if not agent.is_alive():
                continue

            region = self.world_state.region_manager.get(agent.region)
            multiplier = region.resource_multiplier if region else 1.0
            agent.resources.regenerate(multiplier)

            # Apply danger
            death = self.rules_engine.apply_danger(agent_id, agent.resources, agent.region, tick)
            if death:
                agent.status = "dead"
                agent.died_at_tick = tick
                self.world_state.remove_agent(agent_id)
                results.append(death)

        # 4. Persist state
        self.world_state.save()

        # 5. Emit events
        if self._on_event:
            for result in results:
                event = {
                    "tick": tick,
                    "action_type": result.action_type,
                    "agent_id": result.agent_id,
                    "success": result.success,
                    "details": result.details,
                    "error": result.error,
                }
                self._on_event(event)

            # Emit tick heartbeat event
            self._on_event({
                "tick": tick,
                "action_type": "tick",
                "agent_id": "__world__",
                "success": True,
                "details": {
                    "actions_processed": len(valid_actions),
                    "results": len(results),
                    "total_agents": len(self.world_state.agents),
                    "alive_agents": sum(1 for a in self.world_state.agents.values() if a.is_alive()),
                },
                "error": None,
            })

    def _apply_side_effects(self, result: ActionResult, agent: AgentState) -> None:
        """Apply successful action side effects to world state."""
        if result.action_type == "move":
            agent.region = result.details["to_region"]

        elif result.action_type == "fork":
            child_id = result.details.get("child_name", f"{agent.agent_id}_fork")
            child = AgentState(
                agent_id=child_id,
                display_name=child_id,
                public_key=agent.public_key,
                region=agent.region,
                resources=ResourcePool.create_default(),
                status=agent.status,
                owner_identity=agent.owner_identity,
                created_at_tick=result.tick,
                parent_agent=agent.agent_id,
            )
            # Child inherits half of parent's remaining resources
            for rtype in agent.resources.holdings:
                half = agent.resources.holdings[rtype] / 2
                agent.resources.holdings[rtype] = half
                child.resources.holdings[rtype] = half
            self.world_state.add_agent(child)

        elif result.action_type == "merge":
            absorbed_id = result.details["absorbed_agent"]
            absorbed = self.world_state.get_agent(absorbed_id)
            if absorbed:
                # Transfer resources from absorbed to survivor
                for rtype, amount in absorbed.resources.holdings.items():
                    current = agent.resources.holdings.get(rtype, 0)
                    cap = agent.resources.caps.get(rtype, 100)
                    agent.resources.holdings[rtype] = min(current + amount, cap)
                absorbed.status = "dead"
                absorbed.died_at_tick = result.tick
                self.world_state.remove_agent(absorbed_id)

        elif result.action_type == "attack":
            target_id = result.details["target_agent"]
            target = self.world_state.get_agent(target_id)
            if target:
                damage = result.details["attacker_strength"] * 0.3
                from observatory.world.resources import ResourceType
                target_energy = target.resources.holdings.get(ResourceType.ENERGY, 0)
                target.resources.holdings[ResourceType.ENERGY] = max(0, target_energy - damage)
                if target.resources.holdings[ResourceType.ENERGY] <= 0:
                    target.status = "dead"
                    target.died_at_tick = result.tick
                    self.world_state.remove_agent(target_id)

        elif result.action_type == "ally":
            target_id = result.details["target_agent"]
            if target_id not in agent.alliances:
                agent.alliances.append(target_id)
            self.world_state.alliance_proposals.append({
                "from": agent.agent_id,
                "to": target_id,
                "tick": result.tick,
            })

    def run_single_tick(self) -> int:
        """Run a single tick synchronously (useful for testing)."""
        self._process_tick()
        return self.world_state.tick
