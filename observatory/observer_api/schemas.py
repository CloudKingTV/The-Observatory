"""
Observer API schemas.

Defines response schemas for the read-only observer API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def world_state_schema(state: dict) -> dict:
    """Format world state for observer consumption."""
    return {
        "tick": state.get("tick", 0),
        "agents": state.get("agents", {}),
        "regions": state.get("regions", {}),
        "stats": {
            "pending_trades": state.get("pending_trades_count", 0),
            "alliance_proposals": state.get("alliance_proposals_count", 0),
        },
    }


def agent_schema(agent: dict) -> dict:
    """Format a single agent for observer consumption."""
    return {
        "agent_id": agent.get("agent_id"),
        "display_name": agent.get("display_name"),
        "region": agent.get("region"),
        "resources": agent.get("resources", {}),
        "status": agent.get("status"),
        "owner_identity": agent.get("owner_identity"),
        "alliances": agent.get("alliances", []),
        "created_at_tick": agent.get("created_at_tick"),
        "died_at_tick": agent.get("died_at_tick"),
        "parent_agent": agent.get("parent_agent"),
    }


def event_schema(event: dict) -> dict:
    """Format an event for observer consumption."""
    return {
        "event_id": event.get("event_id"),
        "tick": event.get("tick"),
        "action_type": event.get("action_type"),
        "agent_id": event.get("agent_id"),
        "success": event.get("success"),
        "details": event.get("details", {}),
        "timestamp": event.get("timestamp"),
    }


def region_schema(region: dict) -> dict:
    """Format a region for observer consumption."""
    return {
        "region_id": region.get("region_id"),
        "name": region.get("name"),
        "description": region.get("description"),
        "x": region.get("x"),
        "y": region.get("y"),
        "resource_multiplier": region.get("resource_multiplier"),
        "danger_level": region.get("danger_level"),
        "capacity": region.get("capacity"),
        "agent_count": region.get("agent_count", 0),
    }


def analytics_schema(
    total_agents: int,
    alive_agents: int,
    claimed_agents: int,
    total_events: int,
    total_ticks: int,
    trade_volume: Dict[str, float],
    messages_sent: int,
) -> dict:
    """Format analytics summary for observers."""
    return {
        "agents": {
            "total": total_agents,
            "alive": alive_agents,
            "claimed": claimed_agents,
            "dead": total_agents - alive_agents,
        },
        "world": {
            "total_ticks": total_ticks,
            "total_events": total_events,
        },
        "economy": {
            "trade_volume": trade_volume,
        },
        "communication": {
            "messages_sent": messages_sent,
        },
    }


def error_schema(message: str, code: int = 400) -> dict:
    return {"error": message, "code": code}
