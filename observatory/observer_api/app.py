"""
Observer API — READ-ONLY endpoints for humans.

This API must NEVER mutate world state.
No write routes. No shared credentials with Agent Gateway.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from observatory.observer_api.schemas import (
    agent_schema,
    analytics_schema,
    error_schema,
    event_schema,
    region_schema,
    world_state_schema,
)


def create_observer_routes(world_state, event_ledger, replay_engine, accounting, message_bus):
    """Create observer routes bound to the given state objects. Returns a new blueprint each time."""
    observer_bp = Blueprint("observer", __name__, url_prefix="/api/observer")

    @observer_bp.route("/world/state", methods=["GET"])
    def get_world_state():
        """GET /api/observer/world/state — Full world snapshot."""
        snapshot = world_state.snapshot()
        return jsonify(world_state_schema(snapshot))

    @observer_bp.route("/world/regions", methods=["GET"])
    def get_world_regions():
        """GET /api/observer/world/regions — All regions."""
        regions = world_state.region_manager.to_dict()
        return jsonify({
            rid: region_schema(rdata) for rid, rdata in regions.items()
        })

    @observer_bp.route("/ledger/events", methods=["GET"])
    def get_ledger_events():
        """GET /api/observer/ledger/events — Query event ledger."""
        from_tick = request.args.get("from", 0, type=int)
        to_tick = request.args.get("to", None, type=int)
        action_type = request.args.get("action_type", None)
        agent_id = request.args.get("agent_id", None)
        limit = request.args.get("limit", 100, type=int)
        limit = min(limit, 1000)  # Cap at 1000

        events = event_ledger.get_events(
            from_tick=from_tick,
            to_tick=to_tick,
            action_type=action_type,
            agent_id=agent_id,
            limit=limit,
        )
        return jsonify({
            "events": [event_schema(e.to_dict()) for e in events],
            "count": len(events),
        })

    @observer_bp.route("/agents/<agent_id>", methods=["GET"])
    def get_agent(agent_id):
        """GET /api/observer/agents/<id> — Single agent info."""
        agent = world_state.get_agent(agent_id)
        if not agent:
            return jsonify(error_schema("Agent not found", 404)), 404
        return jsonify(agent_schema(agent.public_dict()))

    @observer_bp.route("/agents", methods=["GET"])
    def get_all_agents():
        """GET /api/observer/agents — All agents."""
        agents = {
            aid: agent_schema(a.public_dict())
            for aid, a in world_state.agents.items()
        }
        return jsonify(agents)

    @observer_bp.route("/analytics/summary", methods=["GET"])
    def get_analytics_summary():
        """GET /api/observer/analytics/summary — World analytics."""
        total = len(world_state.agents)
        alive = sum(1 for a in world_state.agents.values() if a.is_alive())
        claimed = sum(1 for a in world_state.agents.values() if a.is_claimed())
        total_events = event_ledger.count()
        total_ticks = world_state.tick
        trade_volume = accounting.total_volume()
        messages = message_bus.message_count()

        return jsonify(analytics_schema(
            total, alive, claimed, total_events, total_ticks, trade_volume, messages,
        ))

    @observer_bp.route("/replay/<int:tick>", methods=["GET"])
    def get_replay_at_tick(tick):
        """GET /api/observer/replay/<tick> — Reconstruct state at tick."""
        result = replay_engine.reconstruct_at_tick(tick)
        return jsonify(result)

    @observer_bp.route("/timeline/<agent_id>", methods=["GET"])
    def get_agent_timeline(agent_id):
        """GET /api/observer/timeline/<agent_id> — Agent event timeline."""
        from_tick = request.args.get("from", 0, type=int)
        to_tick = request.args.get("to", None, type=int)
        timeline = replay_engine.get_timeline(agent_id, from_tick, to_tick)
        return jsonify({"agent_id": agent_id, "events": timeline})

    @observer_bp.route("/timeline", methods=["GET"])
    def get_world_timeline():
        """GET /api/observer/timeline — World event timeline."""
        from_tick = request.args.get("from", 0, type=int)
        to_tick = request.args.get("to", None, type=int)
        limit = request.args.get("limit", 100, type=int)
        timeline = replay_engine.get_world_timeline(from_tick, to_tick, limit)
        return jsonify({"events": timeline})

    # Ensure no write methods exist on observer routes
    @observer_bp.after_request
    def enforce_read_only(response):
        """Safety: reject any non-GET request that somehow reaches observer."""
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return jsonify(error_schema("Observer API is read-only", 405)), 405
        return response

    return observer_bp
