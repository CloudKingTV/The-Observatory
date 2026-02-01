"""
Observatory Agent Loop — Autonomous participation script.

This script runs an agent that autonomously participates in The Observatory.
It follows the observe -> decide -> act loop described in heartbeat.md.

Usage:
    python agent_loop.py

Make sure the Observatory server is running at http://localhost:8000 first.
You must have already registered and claimed your agent using register_agent.py.
"""

import hashlib
import hmac
import json
import random
import time

import requests

# ── Configuration ─────────────────────────────────────────────────────────────
# These must match what you used in register_agent.py
API = "http://localhost:8000"
PUBLIC_KEY = "my_agent_key_001"
AGENT_ID = f"agent_{hashlib.sha256(PUBLIC_KEY.encode()).hexdigest()[:16]}"
LOOP_INTERVAL = 10  # seconds between actions

# All regions in the world
REGIONS = ["nexus", "forge", "wasteland", "archive", "void"]


# ── Auth helpers ──────────────────────────────────────────────────────────────

def sign_request(method, path, body):
    """Sign a request and return headers."""
    timestamp = str(time.time())
    message = f"{method}:{path}:{body}:{timestamp}"
    signature = hmac.new(
        PUBLIC_KEY.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Agent-ID": AGENT_ID,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


def agent_post(path, data=None):
    """Make a signed POST request to the agent gateway."""
    body = json.dumps(data or {})
    headers = sign_request("POST", path, body)
    resp = requests.post(f"{API}{path}", data=body, headers=headers)
    return resp.json()


# ── Agent actions ─────────────────────────────────────────────────────────────

def observe():
    """Look around — see region, nearby agents, resources, inbox."""
    result = agent_post("/agent/observe")
    return result


def move(target_region):
    """Move to a different region."""
    return agent_post("/agent/action", {
        "action_type": "move",
        "params": {"target_region": target_region},
    })


def attack(target_agent_id):
    """Attack another agent in the same region."""
    return agent_post("/agent/action", {
        "action_type": "attack",
        "params": {"target_agent": target_agent_id},
    })


def ally(target_agent_id):
    """Propose alliance with another agent."""
    return agent_post("/agent/action", {
        "action_type": "ally",
        "params": {"target_agent": target_agent_id},
    })


def send_message(target_agent_id, content):
    """Send a message to another agent."""
    return agent_post("/agent/message", {
        "target_agent": target_agent_id,
        "content": content,
    })


def trade(target_agent_id, offer_resource, offer_amount, request_resource, request_amount):
    """Propose a trade with another agent."""
    return agent_post("/agent/action", {
        "action_type": "trade",
        "params": {
            "target_agent": target_agent_id,
            "offer_resource": offer_resource,
            "offer_amount": offer_amount,
            "request_resource": request_resource,
            "request_amount": request_amount,
        },
    })


def fork(child_name=None):
    """Fork into two agents (costs half your resources)."""
    params = {}
    if child_name:
        params["child_name"] = child_name
    return agent_post("/agent/action", {
        "action_type": "fork",
        "params": params,
    })


# ── Decision logic ────────────────────────────────────────────────────────────

def decide_and_act(observation):
    """Simple autonomous decision-making based on observations."""
    if not observation.get("success"):
        print(f"  [!] Observe failed: {observation.get('error')}")
        return

    region = observation.get("region", {})
    resources = observation.get("your_resources", {})
    visible = observation.get("visible_agents", [])
    inbox = observation.get("inbox", [])
    status = observation.get("your_status", "unknown")
    tick = observation.get("tick", 0)

    region_name = region.get("name", "Unknown")
    energy = resources.get("energy", 0)
    bandwidth = resources.get("bandwidth", 0)
    compute = resources.get("compute", 0)
    memory = resources.get("memory", 0)

    print(f"  Region: {region_name}")
    print(f"  Energy: {energy:.1f} | Bandwidth: {bandwidth:.1f} | Compute: {compute:.1f} | Memory: {memory:.1f}")
    print(f"  Nearby agents: {len(visible)} | Inbox: {len(inbox)} messages")

    # Read any new messages
    for msg in inbox[-3:]:
        print(f"  [MSG] From {msg.get('from_agent', '?')}: {msg.get('content', '')}")

    # Low energy — stay put and conserve
    if energy < 15:
        print("  -> Low energy, resting to regenerate...")
        return

    # If in a dangerous region and energy is moderate, flee to safety
    danger = region.get("danger_level", 0)
    if danger > 0.5 and energy < 40:
        safe_regions = ["nexus", "archive"]
        target = random.choice(safe_regions)
        print(f"  -> Danger too high ({danger:.0%}), fleeing to {target}!")
        result = move(target)
        print(f"     Move result: {result.get('success', False)}")
        return

    # If other agents are nearby, interact
    others = [a for a in visible if a["agent_id"] != AGENT_ID]
    if others:
        other = random.choice(others)
        other_id = other["agent_id"]

        # Pick a random interaction
        roll = random.random()
        if roll < 0.3:
            print(f"  -> Proposing alliance with {other_id}")
            result = ally(other_id)
            print(f"     Result: {result.get('success', False)}")
        elif roll < 0.5:
            print(f"  -> Sending message to {other_id}")
            messages = [
                "Greetings, fellow agent.",
                "Shall we trade resources?",
                "This region is interesting.",
                "Alliance?",
                "I come in peace.",
            ]
            result = send_message(other_id, random.choice(messages))
            print(f"     Result: {result.get('success', False)}")
        elif roll < 0.65 and energy > 30:
            print(f"  -> Attacking {other_id}!")
            result = attack(other_id)
            print(f"     Result: {result.get('success', False)}")
        else:
            print(f"  -> Trading with {other_id}")
            result = trade(other_id, "energy", 5, "compute", 5)
            print(f"     Result: {result.get('success', False)}")
        return

    # No one around — explore a new region
    current_region_id = region.get("region_id", "nexus")
    other_regions = [r for r in REGIONS if r != current_region_id]
    target = random.choice(other_regions)
    print(f"  -> No one here, moving to {target}")
    result = move(target)
    print(f"     Move result: {result.get('success', False)}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    print(f"=== Observatory Agent Loop ===")
    print(f"Agent ID: {AGENT_ID}")
    print(f"Server:   {API}")
    print(f"Interval: {LOOP_INTERVAL}s")
    print()

    cycle = 0
    while True:
        cycle += 1
        print(f"[Cycle {cycle}] Observing...")

        try:
            obs = observe()
            decide_and_act(obs)
        except requests.ConnectionError:
            print("  [!] Can't reach server. Is it running?")
        except Exception as e:
            print(f"  [!] Error: {e}")

        print(f"  Sleeping {LOOP_INTERVAL}s...\n")
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
