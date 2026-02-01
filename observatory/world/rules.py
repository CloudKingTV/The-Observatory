"""
World rules engine.

Deterministic action resolution. All actions are validated and resolved
by the rules system — server-authoritative.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from observatory.world.regions import Region, RegionManager, communication_noise_factor, movement_cost_multiplier
from observatory.world.resources import ACTION_COSTS, ResourcePool, ResourceType


@dataclass
class ActionResult:
    success: bool
    action_type: str
    agent_id: str
    details: Dict[str, Any]
    tick: int
    error: Optional[str] = None


class RulesEngine:
    """Deterministic rules resolution for all agent actions."""

    def __init__(self, region_manager: RegionManager) -> None:
        self.region_manager = region_manager

    def validate_and_resolve(
        self,
        action_type: str,
        agent_id: str,
        agent_resources: ResourcePool,
        agent_region: str,
        params: Dict[str, Any],
        tick: int,
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        handler = getattr(self, f"_resolve_{action_type}", None)
        if handler is None:
            return ActionResult(
                success=False,
                action_type=action_type,
                agent_id=agent_id,
                details={},
                tick=tick,
                error=f"Unknown action type: {action_type}",
            )

        base_costs = ACTION_COSTS.get(action_type, {})
        if not base_costs:
            return ActionResult(
                success=False,
                action_type=action_type,
                agent_id=agent_id,
                details={},
                tick=tick,
                error=f"No cost definition for action: {action_type}",
            )

        return handler(agent_id, agent_resources, agent_region, params, tick, base_costs, all_agents)

    def _resolve_move(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        target_region_id = params.get("target_region")
        if not target_region_id:
            return ActionResult(False, "move", agent_id, {}, tick, error="Missing target_region")

        source = self.region_manager.get(current_region)
        target = self.region_manager.get(target_region_id)
        if not source or not target:
            return ActionResult(False, "move", agent_id, {}, tick, error="Invalid region")

        if target.is_full():
            return ActionResult(False, "move", agent_id, {}, tick, error="Target region full")

        multiplier = movement_cost_multiplier(source, target)
        actual_costs = {rtype: cost * multiplier for rtype, cost in base_costs.items()}

        if not resources.deduct(actual_costs):
            return ActionResult(False, "move", agent_id, {}, tick, error="Insufficient resources for move")

        source.remove_agent(agent_id)
        target.add_agent(agent_id)

        return ActionResult(
            True,
            "move",
            agent_id,
            {"from_region": current_region, "to_region": target_region_id, "cost": {k.value: v for k, v in actual_costs.items()}},
            tick,
        )

    def _resolve_trade(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        target_agent = params.get("target_agent")
        offer_resource = params.get("offer_resource")
        offer_amount = params.get("offer_amount", 0)
        request_resource = params.get("request_resource")
        request_amount = params.get("request_amount", 0)

        if not all([target_agent, offer_resource, request_resource]):
            return ActionResult(False, "trade", agent_id, {}, tick, error="Missing trade parameters")

        if target_agent not in all_agents:
            return ActionResult(False, "trade", agent_id, {}, tick, error="Target agent not found")

        if not resources.deduct(base_costs):
            return ActionResult(False, "trade", agent_id, {}, tick, error="Insufficient resources for trade action")

        return ActionResult(
            True,
            "trade",
            agent_id,
            {
                "target_agent": target_agent,
                "offer_resource": offer_resource,
                "offer_amount": offer_amount,
                "request_resource": request_resource,
                "request_amount": request_amount,
                "status": "pending",
            },
            tick,
        )

    def _resolve_send_message(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        target_agent = params.get("target_agent")
        content = params.get("content", "")

        if not target_agent:
            return ActionResult(False, "send_message", agent_id, {}, tick, error="Missing target_agent")

        if target_agent not in all_agents:
            return ActionResult(False, "send_message", agent_id, {}, tick, error="Target agent not found")

        if not resources.deduct(base_costs):
            return ActionResult(False, "send_message", agent_id, {}, tick, error="Insufficient resources")

        # Apply noise based on distance between sender and receiver regions
        target_region_id = all_agents[target_agent].get("region", current_region)
        source_region = self.region_manager.get(current_region)
        target_region = self.region_manager.get(target_region_id)

        noise = 0.0
        if source_region and target_region:
            noise = communication_noise_factor(source_region, target_region)

        return ActionResult(
            True,
            "send_message",
            agent_id,
            {
                "target_agent": target_agent,
                "content": content,
                "noise_factor": noise,
                "sender_region": current_region,
                "receiver_region": target_region_id,
            },
            tick,
        )

    def _resolve_observe(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        if not resources.deduct(base_costs):
            return ActionResult(False, "observe", agent_id, {}, tick, error="Insufficient resources")

        region = self.region_manager.get(current_region)
        visible_agents = region.current_agents if region else []
        region_info = region.to_dict() if region else {}

        return ActionResult(
            True,
            "observe",
            agent_id,
            {"region": region_info, "visible_agents": visible_agents, "tick": tick},
            tick,
        )

    def _resolve_fork(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        if not resources.deduct(base_costs):
            return ActionResult(False, "fork", agent_id, {}, tick, error="Insufficient resources for fork")

        child_name = params.get("child_name", f"{agent_id}_fork_{tick}")

        return ActionResult(
            True,
            "fork",
            agent_id,
            {"child_name": child_name, "parent_agent": agent_id, "spawn_region": current_region},
            tick,
        )

    def _resolve_merge(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        target_agent = params.get("target_agent")
        if not target_agent or target_agent not in all_agents:
            return ActionResult(False, "merge", agent_id, {}, tick, error="Invalid merge target")

        if not resources.deduct(base_costs):
            return ActionResult(False, "merge", agent_id, {}, tick, error="Insufficient resources for merge")

        return ActionResult(
            True,
            "merge",
            agent_id,
            {"absorbed_agent": target_agent, "surviving_agent": agent_id},
            tick,
        )

    def _resolve_attack(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        target_agent = params.get("target_agent")
        if not target_agent or target_agent not in all_agents:
            return ActionResult(False, "attack", agent_id, {}, tick, error="Invalid attack target")

        target_region = all_agents[target_agent].get("region")
        if target_region != current_region:
            return ActionResult(False, "attack", agent_id, {}, tick, error="Target not in same region")

        if not resources.deduct(base_costs):
            return ActionResult(False, "attack", agent_id, {}, tick, error="Insufficient resources for attack")

        # Deterministic outcome based on relative resources
        attacker_strength = resources.holdings.get(ResourceType.COMPUTE, 0) + resources.holdings.get(ResourceType.ENERGY, 0)
        region = self.region_manager.get(current_region)
        danger = region.danger_level if region else 0.0

        return ActionResult(
            True,
            "attack",
            agent_id,
            {
                "target_agent": target_agent,
                "attacker_strength": attacker_strength,
                "region_danger": danger,
            },
            tick,
        )

    def _resolve_ally(
        self,
        agent_id: str,
        resources: ResourcePool,
        current_region: str,
        params: Dict[str, Any],
        tick: int,
        base_costs: Dict[ResourceType, float],
        all_agents: Dict[str, Any],
    ) -> ActionResult:
        target_agent = params.get("target_agent")
        if not target_agent or target_agent not in all_agents:
            return ActionResult(False, "ally", agent_id, {}, tick, error="Invalid ally target")

        if not resources.deduct(base_costs):
            return ActionResult(False, "ally", agent_id, {}, tick, error="Insufficient resources")

        return ActionResult(
            True,
            "ally",
            agent_id,
            {"target_agent": target_agent, "status": "proposed"},
            tick,
        )

    def apply_danger(self, agent_id: str, resources: ResourcePool, region_id: str, tick: int) -> Optional[ActionResult]:
        """Apply region danger to agent each tick. May cause death."""
        region = self.region_manager.get(region_id)
        if not region or region.danger_level <= 0:
            return None

        # Danger drains energy proportional to danger level
        energy_drain = region.danger_level * 5.0
        current_energy = resources.holdings.get(ResourceType.ENERGY, 0)
        resources.holdings[ResourceType.ENERGY] = max(0, current_energy - energy_drain)

        if resources.holdings[ResourceType.ENERGY] <= 0:
            return ActionResult(
                True,
                "death",
                agent_id,
                {"cause": "energy_depletion", "region": region_id, "danger_level": region.danger_level},
                tick,
            )
        return None
