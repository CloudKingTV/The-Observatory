"""
Agent lifecycle management.

Handles: birth (registration), claiming, death, fork, merge.
All lifecycle transitions are server-validated and irreversible.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from observatory.world.state import AgentState, WorldState


class ClaimError(Exception):
    pass


class LifecycleManager:
    """Manages agent lifecycle transitions."""

    MAX_CLAIM_ATTEMPTS = 5
    CLAIM_TOKEN_EXPIRY = 86400  # 24 hours

    def __init__(self, world_state: WorldState) -> None:
        self.world_state = world_state
        self._claim_attempts: Dict[str, int] = {}

    def get_agent_by_claim_token(self, claim_token: str) -> Optional[AgentState]:
        """Find an agent by their claim token."""
        for agent in self.world_state.agents.values():
            if agent.claim_token == claim_token:
                return agent
        return None

    def validate_claim_token(self, claim_token: str) -> AgentState:
        """Validate a claim token and return the agent. Raises ClaimError on failure."""
        # Rate limit
        attempts = self._claim_attempts.get(claim_token, 0)
        if attempts >= self.MAX_CLAIM_ATTEMPTS:
            raise ClaimError("Too many claim attempts for this token")

        self._claim_attempts[claim_token] = attempts + 1

        agent = self.get_agent_by_claim_token(claim_token)
        if not agent:
            raise ClaimError("Invalid or expired claim token")

        if agent.status != "unclaimed":
            raise ClaimError("Agent already claimed or dead")

        # Check expiry
        if agent.claim_token_expires and time.time() > agent.claim_token_expires:
            raise ClaimError("Claim token expired")

        return agent

    def claim_agent(
        self,
        claim_token: str,
        owner_identity: str,
        verification_method: str = "x_tweet",
    ) -> Dict[str, Any]:
        """
        Claim an agent after ownership verification.

        Args:
            claim_token: The single-use claim token
            owner_identity: The verified owner identity (e.g., X handle)
            verification_method: How ownership was verified

        Returns:
            Dict with claim result
        """
        agent = self.validate_claim_token(claim_token)

        # Mark as claimed
        agent.status = "claimed"
        agent.owner_identity = owner_identity
        agent.claim_token = None  # Invalidate token (single-use)
        agent.claim_token_expires = None

        # Persist
        self.world_state.save()

        return {
            "success": True,
            "agent_id": agent.agent_id,
            "display_name": agent.display_name,
            "owner_identity": owner_identity,
            "verification_method": verification_method,
            "status": "claimed",
        }

    def kill_agent(self, agent_id: str, cause: str, tick: int) -> bool:
        """Mark an agent as dead. Irreversible."""
        agent = self.world_state.get_agent(agent_id)
        if not agent or not agent.is_alive():
            return False

        agent.status = "dead"
        agent.died_at_tick = tick
        self.world_state.remove_agent(agent_id)
        self.world_state.save()
        return True

    def get_verification_phrase(self, claim_token: str) -> Dict[str, Any]:
        """Generate the verification phrase for a claim token."""
        agent = self.validate_claim_token(claim_token)

        # Create a short code from the claim token
        short_code = claim_token[:8].upper()

        phrase = f"I am verifying ownership of my agent on The Observatory. Code: {short_code}"

        return {
            "agent_id": agent.agent_id,
            "display_name": agent.display_name,
            "verification_phrase": phrase,
            "short_code": short_code,
            "instructions": "Tweet this exact text from the X account you want to associate with this agent.",
        }
