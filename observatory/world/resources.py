"""
World resource system.

Defines scarce resources that constrain agent behavior:
energy, bandwidth, memory, compute.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict


class ResourceType(str, enum.Enum):
    ENERGY = "energy"
    BANDWIDTH = "bandwidth"
    MEMORY = "memory"
    COMPUTE = "compute"


# Default caps and regeneration rates per tick
RESOURCE_DEFAULTS: Dict[ResourceType, Dict[str, float]] = {
    ResourceType.ENERGY: {"cap": 100.0, "regen": 2.0, "initial": 50.0},
    ResourceType.BANDWIDTH: {"cap": 50.0, "regen": 1.0, "initial": 25.0},
    ResourceType.MEMORY: {"cap": 200.0, "regen": 0.0, "initial": 100.0},
    ResourceType.COMPUTE: {"cap": 80.0, "regen": 1.5, "initial": 40.0},
}

# Costs for standard actions
ACTION_COSTS: Dict[str, Dict[ResourceType, float]] = {
    "move": {ResourceType.ENERGY: 5.0},
    "trade": {ResourceType.ENERGY: 2.0, ResourceType.BANDWIDTH: 3.0},
    "send_message": {ResourceType.BANDWIDTH: 5.0, ResourceType.ENERGY: 1.0},
    "observe": {ResourceType.ENERGY: 1.0},
    "fork": {ResourceType.ENERGY: 40.0, ResourceType.MEMORY: 50.0, ResourceType.COMPUTE: 30.0},
    "merge": {ResourceType.ENERGY: 20.0, ResourceType.COMPUTE: 20.0},
    "attack": {ResourceType.ENERGY: 15.0, ResourceType.COMPUTE: 10.0},
    "ally": {ResourceType.ENERGY: 3.0, ResourceType.BANDWIDTH: 2.0},
}


@dataclass
class ResourcePool:
    """Tracks an agent's resource holdings."""

    holdings: Dict[ResourceType, float] = field(default_factory=dict)
    caps: Dict[ResourceType, float] = field(default_factory=dict)

    @classmethod
    def create_default(cls) -> "ResourcePool":
        pool = cls()
        for rtype, defaults in RESOURCE_DEFAULTS.items():
            pool.holdings[rtype] = defaults["initial"]
            pool.caps[rtype] = defaults["cap"]
        return pool

    def can_afford(self, costs: Dict[ResourceType, float]) -> bool:
        for rtype, amount in costs.items():
            if self.holdings.get(rtype, 0.0) < amount:
                return False
        return True

    def deduct(self, costs: Dict[ResourceType, float]) -> bool:
        if not self.can_afford(costs):
            return False
        for rtype, amount in costs.items():
            self.holdings[rtype] -= amount
        return True

    def regenerate(self, region_multiplier: float = 1.0) -> None:
        for rtype, defaults in RESOURCE_DEFAULTS.items():
            regen = defaults["regen"] * region_multiplier
            current = self.holdings.get(rtype, 0.0)
            cap = self.caps.get(rtype, defaults["cap"])
            self.holdings[rtype] = min(current + regen, cap)

    def to_dict(self) -> Dict[str, float]:
        return {rtype.value: amount for rtype, amount in self.holdings.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, float], caps: Dict[str, float] | None = None) -> "ResourcePool":
        pool = cls()
        for key, val in data.items():
            rtype = ResourceType(key)
            pool.holdings[rtype] = val
            if caps and key in caps:
                pool.caps[rtype] = caps[key]
            else:
                pool.caps[rtype] = RESOURCE_DEFAULTS.get(rtype, {}).get("cap", 100.0)
        return pool
