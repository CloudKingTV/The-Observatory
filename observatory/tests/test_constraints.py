"""
Tests for core constraints:
1. No human write access
2. Claim token rules (single-use, expiry, rate limit)
3. Signed agent requests
4. Observer API is read-only
5. Unclaimed agents are restricted
"""

import hashlib
import hmac
import json
import os
import tempfile
import time

import pytest

from observatory.web.app import create_app


@pytest.fixture
def app(tmp_path):
    """Create test app with fast tick and isolated state files."""
    os.environ["OBSERVATORY_STATE_FILE"] = str(tmp_path / "test_state.json")
    os.environ["OBSERVATORY_LEDGER_FILE"] = str(tmp_path / "test_ledger.jsonl")
    app = create_app(tick_duration=999)  # Don't auto-tick in tests
    app.config["TESTING"] = True
    # Stop the engine to prevent background ticks
    app.engine.stop()
    yield app
    # Cleanup
    os.environ.pop("OBSERVATORY_STATE_FILE", None)
    os.environ.pop("OBSERVATORY_LEDGER_FILE", None)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def registered_agent(client):
    """Register an agent and return its credentials."""
    public_key = "test_agent_key_001"
    nonce = "test_nonce_12345"

    # Get PoW challenge
    resp = client.post("/agent/register/challenge")
    data = resp.get_json()
    challenge = data["challenge"]

    # Solve PoW
    from observatory.agents.identity import AntiSybil
    pow_nonce = AntiSybil.solve_pow(challenge)

    # Sign nonce
    signed_nonce = hmac.new(
        public_key.encode(), nonce.encode(), hashlib.sha256
    ).hexdigest()

    # Register
    resp = client.post("/agent/register", json={
        "agent_public_key": public_key,
        "agent_display_name": "TestAgent",
        "nonce": nonce,
        "signed_nonce": signed_nonce,
        "pow_challenge": challenge,
        "pow_nonce": pow_nonce,
    })
    data = resp.get_json()
    assert data["success"] is True

    return {
        "agent_id": data["agent_id"],
        "public_key": public_key,
        "claim_token": data["claim_token"],
        "claim_url": data["claim_url"],
    }


def sign_request(public_key, method, path, body, timestamp):
    """Helper: create HMAC signature for agent request."""
    message = f"{method}:{path}:{body}:{timestamp}"
    return hmac.new(
        public_key.encode(), message.encode(), hashlib.sha256
    ).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. NO HUMAN WRITE ACCESS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoHumanWriteAccess:
    """Verify humans cannot write to agent/world endpoints."""

    def test_observer_api_rejects_post(self, client):
        """Observer API must reject all POST/PUT/DELETE."""
        for path in ["/api/observer/world/state", "/api/observer/agents", "/api/observer/ledger/events"]:
            resp = client.post(path)
            assert resp.status_code in (404, 405), f"POST to {path} should be rejected"

    def test_observer_api_rejects_put(self, client):
        for path in ["/api/observer/world/state", "/api/observer/agents"]:
            resp = client.put(path)
            assert resp.status_code in (404, 405), f"PUT to {path} should be rejected"

    def test_observer_api_rejects_delete(self, client):
        for path in ["/api/observer/world/state", "/api/observer/agents"]:
            resp = client.delete(path)
            assert resp.status_code in (404, 405), f"DELETE to {path} should be rejected"

    def test_observer_state_is_get_only(self, client):
        resp = client.get("/api/observer/world/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tick" in data

    def test_agent_endpoints_require_auth(self, client):
        """Agent write endpoints must require authentication."""
        resp = client.post("/agent/observe", json={})
        assert resp.status_code == 401

        resp = client.post("/agent/action", json={"action_type": "move"})
        assert resp.status_code == 401

        resp = client.post("/agent/message", json={"target_agent": "x", "content": "hi"})
        assert resp.status_code == 401

    def test_homepage_is_read_only(self, client):
        """Human-facing pages are GET only."""
        resp = client.get("/")
        assert resp.status_code == 200

        resp = client.get("/register")
        assert resp.status_code == 200

    def test_no_write_route_in_observer(self, client, app):
        """Verify no POST/PUT/DELETE/PATCH routes exist in observer blueprint."""
        observer_rules = [
            rule for rule in app.url_map.iter_rules()
            if rule.rule.startswith("/api/observer")
        ]
        for rule in observer_rules:
            write_methods = {"POST", "PUT", "DELETE", "PATCH"} & set(rule.methods)
            assert not write_methods, f"Observer route {rule.rule} has write methods: {write_methods}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CLAIM TOKEN RULES
# ═══════════════════════════════════════════════════════════════════════════════

class TestClaimTokenRules:
    """Verify claim token security properties."""

    def test_claim_token_works(self, client, registered_agent):
        """Valid claim token should show verification page."""
        claim_token = registered_agent["claim_token"]
        resp = client.get(f"/claim/{claim_token}")
        assert resp.status_code == 200
        assert b"verification" in resp.data.lower() or b"Verification" in resp.data

    def test_invalid_claim_token(self, client):
        """Invalid claim token should fail."""
        resp = client.get("/claim/invalid_token_12345")
        assert resp.status_code == 400

    def test_claim_token_single_use(self, client, registered_agent, app):
        """Claim token should be invalidated after use."""
        claim_token = registered_agent["claim_token"]

        # First claim should succeed
        resp = client.post(f"/claim/{claim_token}/verify", data={
            "owner_identity": "@testuser",
            "verification_method": "x_tweet",
        })
        assert resp.status_code == 200

        # Agent should be claimed
        agent = app.world_state.get_agent(registered_agent["agent_id"])
        assert agent.status == "claimed"

        # Second claim attempt should fail (token invalidated)
        resp = client.get(f"/claim/{claim_token}")
        assert resp.status_code == 400

    def test_claim_requires_owner_identity(self, client, registered_agent):
        """Claim verification requires owner identity."""
        claim_token = registered_agent["claim_token"]
        resp = client.post(f"/claim/{claim_token}/verify", data={
            "owner_identity": "",
            "verification_method": "x_tweet",
        })
        assert resp.status_code == 400

    def test_claim_token_expiry(self, client, registered_agent, app):
        """Expired claim tokens should be rejected."""
        agent = app.world_state.get_agent(registered_agent["agent_id"])
        # Force expire
        agent.claim_token_expires = time.time() - 1

        resp = client.get(f"/claim/{registered_agent['claim_token']}")
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SIGNED AGENT REQUESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSignedAgentRequests:
    """Verify agent authentication via signed requests."""

    def test_valid_signed_request(self, client, registered_agent):
        """Agent with valid signature should be able to observe."""
        agent_id = registered_agent["agent_id"]
        public_key = registered_agent["public_key"]
        timestamp = str(time.time())
        body = "{}"
        signature = sign_request(public_key, "POST", "/agent/observe", body, timestamp)

        resp = client.post("/agent/observe",
            data=body,
            content_type="application/json",
            headers={
                "X-Agent-ID": agent_id,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_missing_auth_headers(self, client, registered_agent):
        """Missing auth headers should return 401."""
        resp = client.post("/agent/observe", json={})
        assert resp.status_code == 401

    def test_invalid_signature(self, client, registered_agent):
        """Invalid signature should return 403."""
        agent_id = registered_agent["agent_id"]
        timestamp = str(time.time())

        resp = client.post("/agent/observe",
            data="{}",
            content_type="application/json",
            headers={
                "X-Agent-ID": agent_id,
                "X-Timestamp": timestamp,
                "X-Signature": "invalid_signature",
            },
        )
        assert resp.status_code == 403

    def test_expired_timestamp(self, client, registered_agent):
        """Expired timestamp should be rejected."""
        agent_id = registered_agent["agent_id"]
        public_key = registered_agent["public_key"]
        timestamp = str(time.time() - 600)  # 10 minutes old
        body = "{}"
        signature = sign_request(public_key, "POST", "/agent/observe", body, timestamp)

        resp = client.post("/agent/observe",
            data=body,
            content_type="application/json",
            headers={
                "X-Agent-ID": agent_id,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
        )
        assert resp.status_code == 403

    def test_wrong_agent_id(self, client, registered_agent):
        """Request with wrong agent_id should fail."""
        public_key = registered_agent["public_key"]
        timestamp = str(time.time())
        body = "{}"
        signature = sign_request(public_key, "POST", "/agent/observe", body, timestamp)

        resp = client.post("/agent/observe",
            data=body,
            content_type="application/json",
            headers={
                "X-Agent-ID": "nonexistent_agent",
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 4. UNCLAIMED AGENT RESTRICTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnclaimedRestrictions:
    """Verify unclaimed agents are heavily restricted."""

    def test_unclaimed_can_observe(self, client, registered_agent):
        """Unclaimed agents should be able to observe."""
        agent_id = registered_agent["agent_id"]
        public_key = registered_agent["public_key"]
        timestamp = str(time.time())
        body = "{}"
        signature = sign_request(public_key, "POST", "/agent/observe", body, timestamp)

        resp = client.post("/agent/observe",
            data=body,
            content_type="application/json",
            headers={
                "X-Agent-ID": agent_id,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
        )
        assert resp.status_code == 200

    def test_unclaimed_cannot_act(self, client, registered_agent):
        """Unclaimed agents should NOT be able to perform actions."""
        agent_id = registered_agent["agent_id"]
        public_key = registered_agent["public_key"]
        body = json.dumps({"action_type": "move", "params": {"target_region": "forge"}})
        timestamp = str(time.time())
        signature = sign_request(public_key, "POST", "/agent/action", body, timestamp)

        resp = client.post("/agent/action",
            data=body,
            content_type="application/json",
            headers={
                "X-Agent-ID": agent_id,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
        )
        data = resp.get_json()
        assert data["success"] is False
        assert "unclaimed" in data.get("error", "").lower()

    def test_unclaimed_cannot_message(self, client, registered_agent):
        """Unclaimed agents should NOT be able to send messages."""
        agent_id = registered_agent["agent_id"]
        public_key = registered_agent["public_key"]
        body = json.dumps({"target_agent": "someone", "content": "hello"})
        timestamp = str(time.time())
        signature = sign_request(public_key, "POST", "/agent/message", body, timestamp)

        resp = client.post("/agent/message",
            data=body,
            content_type="application/json",
            headers={
                "X-Agent-ID": agent_id,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
        )
        data = resp.get_json()
        assert data["success"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. REGISTRATION + ANTI-SYBIL
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistration:
    """Verify registration flow with PoW anti-sybil."""

    def test_registration_requires_pow(self, client):
        """Registration without valid PoW should fail."""
        resp = client.post("/agent/register", json={
            "agent_public_key": "somekey",
            "nonce": "nonce",
            "signed_nonce": "sig",
            "pow_challenge": "challenge",
            "pow_nonce": "wrong",
        })
        data = resp.get_json()
        assert data["success"] is False
        assert "proof-of-work" in data.get("error", "").lower()

    def test_registration_requires_valid_signature(self, client):
        """Registration with invalid signature should fail."""
        from observatory.agents.identity import AntiSybil
        challenge = AntiSybil.generate_challenge()
        pow_nonce = AntiSybil.solve_pow(challenge)

        resp = client.post("/agent/register", json={
            "agent_public_key": "somekey",
            "nonce": "nonce",
            "signed_nonce": "invalid_sig",
            "pow_challenge": challenge,
            "pow_nonce": pow_nonce,
        })
        data = resp.get_json()
        assert data["success"] is False
        assert "signature" in data.get("error", "").lower()

    def test_duplicate_registration_fails(self, client, registered_agent):
        """Re-registering the same key should fail."""
        public_key = registered_agent["public_key"]
        nonce = "nonce2"

        resp = client.post("/agent/register/challenge")
        challenge = resp.get_json()["challenge"]

        from observatory.agents.identity import AntiSybil
        pow_nonce = AntiSybil.solve_pow(challenge)
        signed_nonce = hmac.new(
            public_key.encode(), nonce.encode(), hashlib.sha256
        ).hexdigest()

        resp = client.post("/agent/register", json={
            "agent_public_key": public_key,
            "nonce": nonce,
            "signed_nonce": signed_nonce,
            "pow_challenge": challenge,
            "pow_nonce": pow_nonce,
        })
        data = resp.get_json()
        assert data["success"] is False
        assert "already" in data.get("error", "").lower()

    def test_successful_registration_returns_claim_url(self, client, registered_agent):
        """Successful registration should return claim URL."""
        assert registered_agent["claim_token"] is not None
        assert registered_agent["claim_url"] is not None
        assert "/claim/" in registered_agent["claim_url"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SKILL FILES
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkillFiles:
    """Verify public skill files are served correctly."""

    def test_skill_md(self, client):
        resp = client.get("/skill.md")
        assert resp.status_code == 200
        assert b"Observatory" in resp.data
        assert b"/agent/register" in resp.data

    def test_heartbeat_md(self, client):
        resp = client.get("/heartbeat.md")
        assert resp.status_code == 200
        assert b"heartbeat" in resp.data.lower()

    def test_messaging_md(self, client):
        resp = client.get("/messaging.md")
        assert resp.status_code == 200
        assert b"messaging" in resp.data.lower() or b"Messaging" in resp.data

    def test_skill_json(self, client):
        resp = client.get("/skill.json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "endpoints" in data
        assert "auth" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 7. OBSERVER API READ-ONLY
# ═══════════════════════════════════════════════════════════════════════════════

class TestObserverAPI:
    """Verify observer API returns correct data and is read-only."""

    def test_world_state(self, client):
        resp = client.get("/api/observer/world/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tick" in data
        assert "regions" in data

    def test_world_regions(self, client):
        resp = client.get("/api/observer/world/regions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "nexus" in data

    def test_ledger_events(self, client):
        resp = client.get("/api/observer/ledger/events")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "events" in data

    def test_agent_detail(self, client, registered_agent):
        agent_id = registered_agent["agent_id"]
        resp = client.get(f"/api/observer/agents/{agent_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agent_id"] == agent_id

    def test_agent_not_found(self, client):
        resp = client.get("/api/observer/agents/nonexistent")
        assert resp.status_code == 404

    def test_analytics_summary(self, client):
        resp = client.get("/api/observer/analytics/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "agents" in data
        assert "world" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 8. WORLD ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorldEngine:
    """Verify world engine tick processing."""

    def test_tick_advances(self, app):
        tick_before = app.world_state.tick
        app.engine.run_single_tick()
        assert app.world_state.tick == tick_before + 1

    def test_resource_regeneration(self, app, registered_agent):
        agent = app.world_state.get_agent(registered_agent["agent_id"])
        initial_energy = agent.resources.holdings.get(
            __import__("observatory.world.resources", fromlist=["ResourceType"]).ResourceType.ENERGY, 0
        )
        # Drain some energy
        from observatory.world.resources import ResourceType
        agent.resources.holdings[ResourceType.ENERGY] = 10.0
        app.engine.run_single_tick()
        # Energy should have regenerated
        assert agent.resources.holdings[ResourceType.ENERGY] > 10.0
