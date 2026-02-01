"""
Economy accounting system.

Tracks resource transfers, balances, and economic history.
Emergent currencies are allowed — the system only tracks resource flows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from observatory.world.resources import ResourcePool, ResourceType
from observatory.world.state import AgentState, WorldState


@dataclass
class Transaction:
    transaction_id: str
    tick: int
    from_agent: str
    to_agent: str
    resource_type: str
    amount: float
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "tick": self.tick,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "resource_type": self.resource_type,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class AccountingLedger:
    """
    Append-only transaction ledger for the economy.
    Tracks all resource transfers between agents.
    """

    def __init__(self) -> None:
        self._transactions: List[Transaction] = []
        self._next_id: int = 0

    def record_transfer(
        self,
        tick: int,
        from_agent: str,
        to_agent: str,
        resource_type: str,
        amount: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Transaction:
        tx = Transaction(
            transaction_id=f"tx_{self._next_id:08d}",
            tick=tick,
            from_agent=from_agent,
            to_agent=to_agent,
            resource_type=resource_type,
            amount=amount,
            metadata=metadata or {},
        )
        self._transactions.append(tx)
        self._next_id += 1
        return tx

    def get_transactions(
        self,
        from_tick: int = 0,
        to_tick: Optional[int] = None,
        agent_id: Optional[str] = None,
    ) -> List[Transaction]:
        results = []
        for tx in self._transactions:
            if tx.tick < from_tick:
                continue
            if to_tick is not None and tx.tick > to_tick:
                continue
            if agent_id and tx.from_agent != agent_id and tx.to_agent != agent_id:
                continue
            results.append(tx)
        return results

    def get_balance_sheet(self, agent_id: str) -> Dict[str, float]:
        """Calculate net resource flows for an agent."""
        balances: Dict[str, float] = {}
        for tx in self._transactions:
            if tx.from_agent == agent_id:
                balances[tx.resource_type] = balances.get(tx.resource_type, 0) - tx.amount
            if tx.to_agent == agent_id:
                balances[tx.resource_type] = balances.get(tx.resource_type, 0) + tx.amount
        return balances

    def total_volume(self) -> Dict[str, float]:
        """Total traded volume by resource type."""
        volumes: Dict[str, float] = {}
        for tx in self._transactions:
            volumes[tx.resource_type] = volumes.get(tx.resource_type, 0) + tx.amount
        return volumes

    def to_list(self) -> List[dict]:
        return [tx.to_dict() for tx in self._transactions]
