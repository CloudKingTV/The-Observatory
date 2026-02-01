"""
World region system.

Regions define spatial areas within the world.
Proximity affects action cost and communication risk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Region:
    """A discrete spatial zone in the world."""

    region_id: str
    name: str
    description: str = ""
    x: float = 0.0
    y: float = 0.0
    resource_multiplier: float = 1.0  # affects regen rates
    danger_level: float = 0.0  # 0.0 = safe, 1.0 = lethal
    capacity: int = 100  # max agents
    current_agents: List[str] = field(default_factory=list)

    def is_full(self) -> bool:
        return len(self.current_agents) >= self.capacity

    def add_agent(self, agent_id: str) -> bool:
        if self.is_full() or agent_id in self.current_agents:
            return False
        self.current_agents.append(agent_id)
        return True

    def remove_agent(self, agent_id: str) -> bool:
        if agent_id not in self.current_agents:
            return False
        self.current_agents.remove(agent_id)
        return True

    def to_dict(self) -> dict:
        return {
            "region_id": self.region_id,
            "name": self.name,
            "description": self.description,
            "x": self.x,
            "y": self.y,
            "resource_multiplier": self.resource_multiplier,
            "danger_level": self.danger_level,
            "capacity": self.capacity,
            "agent_count": len(self.current_agents),
        }


def distance(a: Region, b: Region) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


def movement_cost_multiplier(a: Region, b: Region) -> float:
    """Cost multiplier for moving between two regions. Further = more expensive."""
    dist = distance(a, b)
    return 1.0 + dist * 0.5


def communication_noise_factor(a: Region, b: Region) -> float:
    """Noise factor for cross-region communication. Further = noisier."""
    dist = distance(a, b)
    return min(dist * 0.1, 0.8)  # cap at 80% noise


# Default world regions
DEFAULT_REGIONS: List[Dict] = [
    {
        "region_id": "nexus",
        "name": "The Nexus",
        "description": "Central hub. Low danger, moderate resources. Spawn point.",
        "x": 0.0,
        "y": 0.0,
        "resource_multiplier": 1.0,
        "danger_level": 0.05,
        "capacity": 200,
    },
    {
        "region_id": "forge",
        "name": "The Forge",
        "description": "High compute region. Rich in compute resources but energy-hungry.",
        "x": 3.0,
        "y": 1.0,
        "resource_multiplier": 1.5,
        "danger_level": 0.2,
        "capacity": 80,
    },
    {
        "region_id": "wasteland",
        "name": "The Wasteland",
        "description": "Dangerous frontier. Scarce resources, high risk, high reward.",
        "x": -4.0,
        "y": 3.0,
        "resource_multiplier": 0.5,
        "danger_level": 0.7,
        "capacity": 50,
    },
    {
        "region_id": "archive",
        "name": "The Archive",
        "description": "Memory-rich zone. High memory capacity, low bandwidth.",
        "x": 1.0,
        "y": -3.0,
        "resource_multiplier": 1.2,
        "danger_level": 0.1,
        "capacity": 100,
    },
    {
        "region_id": "void",
        "name": "The Void",
        "description": "Edge of the world. Minimal resources, maximum danger. Unknown rewards.",
        "x": -2.0,
        "y": -5.0,
        "resource_multiplier": 0.3,
        "danger_level": 0.9,
        "capacity": 30,
    },
]


class RegionManager:
    """Manages all regions in the world."""

    def __init__(self) -> None:
        self.regions: Dict[str, Region] = {}

    def initialize_defaults(self) -> None:
        for r in DEFAULT_REGIONS:
            region = Region(**r)
            self.regions[region.region_id] = region

    def get(self, region_id: str) -> Optional[Region]:
        return self.regions.get(region_id)

    def get_spawn_region(self) -> Region:
        return self.regions["nexus"]

    def all_regions(self) -> List[Region]:
        return list(self.regions.values())

    def to_dict(self) -> Dict[str, dict]:
        return {rid: r.to_dict() for rid, r in self.regions.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, dict]) -> "RegionManager":
        mgr = cls()
        for rid, rdata in data.items():
            agents = rdata.pop("agent_count", 0)
            if "current_agents" not in rdata:
                rdata["current_agents"] = []
            mgr.regions[rid] = Region(**rdata)
        return mgr
