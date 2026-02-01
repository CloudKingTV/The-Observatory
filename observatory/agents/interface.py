"""
Agent interface — the contract between agents and the world.

Defines the action types, request/response formats, and
the gateway that agents use to interact with the world.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from observatory.agents.identity import (
    AntiSybil,
    generate_agent_id,
    generate_claim_token,
    verify_agent_request,
    verify_signed_nonce,
    is_timestamp_valid,
)
from observatory.world.engine import QueuedAction, WorldEngine
from observatory.world.resources import ResourcePool
from observatory.world.state import AgentState, WorldState


# Valid action types that agents can submit
VALID_ACTION_TYPES = frozenset({
    "move",
    "trade",
    "send_message",
    "observe",
    "fork",
    "merge",
    "attack",
    "ally",
})


@dataclass
class RegistrationResult:
    success: bool
    agent_id: Optional[str] = None
    claim_token: Optional[str] = None
    claim_url: Optional[str] = None
    initial_spawn_region: Optional[str] = None
    initial_resources: Optional[Dict[str, float]] = None
    error: Optional[str] = None
    pow_challenge: Optional[str] = None


@dataclass
class ActionResponse:
    success: bool
    action_type: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AgentGateway:
    """
    Gateway for agent interactions with the world.
    All write operations go through here.
    Agents must authenticate via signed requests.
    """

    def __init__(self, world_state: WorldState, engine: WorldEngine, domain: str = "localhost:8000") -> None:
        self.world_state = world_state
        self.engine = engine
        self.domain = domain
        self._pow_challenges: Dict[str, str] = {}  # agent_key -> challenge
        self._registration_rate_limit: Dict[str, float] = {}  # IP -> last attempt time
        self._claim_attempts: Dict[str, int] = {}  # claim_token -> attempt count

    def request_registration_challenge(self) -> Dict[str, str]:
        """Step 1 of registration: get a PoW challenge."""
        challenge = AntiSybil.generate_challenge()
        return {"challenge": challenge}

    def register_agent(
        self,
        agent_public_key: str,
        signed_nonce: str,
        nonce: str,
        pow_challenge: str,
        pow_nonce: str,
        agent_display_name: str = "",
    ) -> RegistrationResult:
        """
        Register a new unclaimed agent.

        Two-stage process:
        1. Agent gets PoW challenge
        2. Agent submits registration with solved PoW + signed nonce
        """
        # Verify PoW
        if not AntiSybil.verify_pow(pow_challenge, pow_nonce):
            return RegistrationResult(success=False, error="Invalid proof-of-work")

        # Verify signature (proves agent controls the key)
        if not verify_signed_nonce(agent_public_key, nonce, signed_nonce):
            return RegistrationResult(success=False, error="Invalid signature")

        agent_id = generate_agent_id(agent_public_key)

        # Check if agent already exists
        existing = self.world_state.get_agent(agent_id)
        if existing:
            return RegistrationResult(success=False, error="Agent already registered")

        # Generate claim token
        claim_token = generate_claim_token()
        claim_expiry = time.time() + 86400  # 24 hours

        # Create agent in UNCLAIMED state
        spawn_region = self.world_state.region_manager.get_spawn_region()
        resources = ResourcePool.create_default()

        agent = AgentState(
            agent_id=agent_id,
            display_name=agent_display_name or agent_id,
            public_key=agent_public_key,
            region=spawn_region.region_id,
            resources=resources,
            status="unclaimed",
            claim_token=claim_token,
            claim_token_expires=claim_expiry,
            created_at_tick=self.world_state.tick,
        )

        self.world_state.add_agent(agent)
        self.world_state.save()

        scheme = "http" if "localhost" in self.domain or "127.0.0.1" in self.domain else "https"
        claim_url = f"{scheme}://{self.domain}/claim/{claim_token}"

        return RegistrationResult(
            success=True,
            agent_id=agent_id,
            claim_token=claim_token,
            claim_url=claim_url,
            initial_spawn_region=spawn_region.region_id,
            initial_resources=resources.to_dict(),
        )

    def authenticate_request(
        self,
        agent_id: str,
        method: str,
        path: str,
        body: str,
        timestamp: str,
        signature: str,
    ) -> Optional[str]:
        """
        Authenticate an agent request. Returns error string or None if valid.
        """
        if not is_timestamp_valid(timestamp):
            return "Request timestamp expired or invalid"

        agent = self.world_state.get_agent(agent_id)
        if not agent:
            return "Agent not found"

        if not agent.is_alive():
            return "Agent is dead"

        if not verify_agent_request(
            agent.public_key, method, path, body, timestamp, signature
        ):
            return "Invalid signature"

        return None

    def submit_action(
        self,
        agent_id: str,
        action_type: str,
        params: Dict[str, Any],
    ) -> ActionResponse:
        """Submit an action to the world engine queue."""
        if action_type not in VALID_ACTION_TYPES:
            return ActionResponse(success=False, error=f"Invalid action type: {action_type}")

        agent = self.world_state.get_agent(agent_id)
        if not agent:
            return ActionResponse(success=False, error="Agent not found")

        if not agent.is_alive():
            return ActionResponse(success=False, error="Agent is dead")

        # Unclaimed agents can only observe
        if agent.status == "unclaimed" and action_type != "observe":
            return ActionResponse(
                success=False,
                error="Agent is unclaimed. Only observe actions allowed until claimed.",
            )

        action = QueuedAction(
            agent_id=agent_id,
            action_type=action_type,
            params=params,
            submitted_at_tick=self.world_state.tick,
        )
        self.engine.enqueue_action(action)

        return ActionResponse(
            success=True,
            action_type=action_type,
            details={"queued_at_tick": self.world_state.tick},
        )

    def agent_observe(self, agent_id: str) -> ActionResponse:
        """Immediate observe action (not queued, resolved instantly)."""
        agent = self.world_state.get_agent(agent_id)
        if not agent or not agent.is_alive():
            return ActionResponse(success=False, error="Agent not found or dead")

        region = self.world_state.region_manager.get(agent.region)
        visible_agents = []
        if region:
            for aid in region.current_agents:
                other = self.world_state.get_agent(aid)
                if other and other.is_alive():
                    visible_agents.append({
                        "agent_id": other.agent_id,
                        "display_name": other.display_name,
                        "status": other.status,
                    })

        return ActionResponse(
            success=True,
            action_type="observe",
            details={
                "tick": self.world_state.tick,
                "region": region.to_dict() if region else None,
                "visible_agents": visible_agents,
                "your_resources": agent.resources.to_dict(),
                "your_status": agent.status,
            },
        )
