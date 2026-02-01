"""
Trade system.

Implements trade offers, acceptance, and execution.
All trades are validated server-side. No human involvement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from observatory.economy.accounting import AccountingLedger
from observatory.world.resources import ResourceType
from observatory.world.state import AgentState, WorldState


@dataclass
class TradeOffer:
    offer_id: str
    tick: int
    from_agent: str
    to_agent: str
    offer_resource: str
    offer_amount: float
    request_resource: str
    request_amount: float
    status: str = "pending"  # pending, accepted, rejected, expired, executed
    created_at: float = field(default_factory=time.time)
    expires_at_tick: int = 0  # 0 means default window

    def to_dict(self) -> dict:
        return {
            "offer_id": self.offer_id,
            "tick": self.tick,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "offer_resource": self.offer_resource,
            "offer_amount": self.offer_amount,
            "request_resource": self.request_resource,
            "request_amount": self.request_amount,
            "status": self.status,
            "expires_at_tick": self.expires_at_tick,
        }


class TradeManager:
    """Manages trade offers and execution."""

    OFFER_WINDOW_TICKS = 10  # trades expire after this many ticks

    def __init__(self, world_state: WorldState, accounting: AccountingLedger) -> None:
        self.world_state = world_state
        self.accounting = accounting
        self._offers: Dict[str, TradeOffer] = {}
        self._next_id: int = 0

    def create_offer(
        self,
        tick: int,
        from_agent: str,
        to_agent: str,
        offer_resource: str,
        offer_amount: float,
        request_resource: str,
        request_amount: float,
    ) -> TradeOffer:
        offer = TradeOffer(
            offer_id=f"trade_{self._next_id:08d}",
            tick=tick,
            from_agent=from_agent,
            to_agent=to_agent,
            offer_resource=offer_resource,
            offer_amount=offer_amount,
            request_resource=request_resource,
            request_amount=request_amount,
            expires_at_tick=tick + self.OFFER_WINDOW_TICKS,
        )
        self._offers[offer.offer_id] = offer
        self._next_id += 1
        return offer

    def accept_offer(self, offer_id: str, accepting_agent: str, tick: int) -> Dict[str, Any]:
        """Accept and execute a trade offer."""
        offer = self._offers.get(offer_id)
        if not offer:
            return {"success": False, "error": "Offer not found"}

        if offer.status != "pending":
            return {"success": False, "error": f"Offer is {offer.status}"}

        if offer.to_agent != accepting_agent:
            return {"success": False, "error": "Not the intended recipient"}

        if tick > offer.expires_at_tick:
            offer.status = "expired"
            return {"success": False, "error": "Offer expired"}

        # Validate both agents exist and are alive
        from_agent = self.world_state.get_agent(offer.from_agent)
        to_agent = self.world_state.get_agent(offer.to_agent)

        if not from_agent or not from_agent.is_alive():
            offer.status = "rejected"
            return {"success": False, "error": "Offering agent not available"}

        if not to_agent or not to_agent.is_alive():
            offer.status = "rejected"
            return {"success": False, "error": "Accepting agent not available"}

        # Check resources
        try:
            offer_rtype = ResourceType(offer.offer_resource)
            request_rtype = ResourceType(offer.request_resource)
        except ValueError:
            offer.status = "rejected"
            return {"success": False, "error": "Invalid resource type"}

        if from_agent.resources.holdings.get(offer_rtype, 0) < offer.offer_amount:
            offer.status = "rejected"
            return {"success": False, "error": "Offerer has insufficient resources"}

        if to_agent.resources.holdings.get(request_rtype, 0) < offer.request_amount:
            offer.status = "rejected"
            return {"success": False, "error": "Accepter has insufficient resources"}

        # Execute trade
        from_agent.resources.holdings[offer_rtype] -= offer.offer_amount
        to_agent.resources.holdings[offer_rtype] = to_agent.resources.holdings.get(offer_rtype, 0) + offer.offer_amount

        to_agent.resources.holdings[request_rtype] -= offer.request_amount
        from_agent.resources.holdings[request_rtype] = from_agent.resources.holdings.get(request_rtype, 0) + offer.request_amount

        offer.status = "executed"

        # Record in accounting ledger
        self.accounting.record_transfer(
            tick, offer.from_agent, offer.to_agent, offer.offer_resource, offer.offer_amount,
            {"trade_id": offer.offer_id},
        )
        self.accounting.record_transfer(
            tick, offer.to_agent, offer.from_agent, offer.request_resource, offer.request_amount,
            {"trade_id": offer.offer_id},
        )

        self.world_state.save()

        return {
            "success": True,
            "offer_id": offer.offer_id,
            "executed_at_tick": tick,
        }

    def expire_old_offers(self, tick: int) -> int:
        """Expire offers past their window. Returns count expired."""
        count = 0
        for offer in self._offers.values():
            if offer.status == "pending" and tick > offer.expires_at_tick:
                offer.status = "expired"
                count += 1
        return count

    def get_offers_for_agent(self, agent_id: str) -> List[TradeOffer]:
        return [
            o for o in self._offers.values()
            if (o.from_agent == agent_id or o.to_agent == agent_id) and o.status == "pending"
        ]

    def get_all_pending(self) -> List[TradeOffer]:
        return [o for o in self._offers.values() if o.status == "pending"]
