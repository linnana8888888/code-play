"""Phase 4.4 tests: agent-to-agent peer review protocol.

Covers:
  - request_peer_review returns a request_id
  - post_peer_review_response resolves the future
  - wait_for_peer_review returns the response when resolved
  - wait_for_peer_review returns None on timeout
  - REST POST /api/projects/{id}/peer-review returns request_id
  - REST POST /api/projects/{id}/peer-review/{id}/respond returns 200
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


# ── MessageBus unit tests ─────────────────────────────────────────────────────


class TestRequestPeerReview:
    @pytest.mark.asyncio
    async def test_returns_request_id(self):
        """request_peer_review returns a non-empty string request_id."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        # Stub out post so we don't need a real DB
        bus.post = AsyncMock(return_value=MagicMock())

        request_id = await bus.request_peer_review(
            project_id="proj-1",
            from_agent="frontend-developer",
            to_agent="code-reviewer",
            question="Is this loop O(n²)?",
            context="See function foo()",
        )

        assert isinstance(request_id, str)
        assert len(request_id) > 0

    @pytest.mark.asyncio
    async def test_request_id_is_unique(self):
        """Each call produces a distinct request_id."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        bus.post = AsyncMock(return_value=MagicMock())

        id1 = await bus.request_peer_review("p", "a1", "a2", "q1")
        id2 = await bus.request_peer_review("p", "a1", "a2", "q2")

        assert id1 != id2

    @pytest.mark.asyncio
    async def test_pending_future_stored(self):
        """A Future is stored under the returned request_id."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        bus.post = AsyncMock(return_value=MagicMock())

        request_id = await bus.request_peer_review("p", "a1", "a2", "q")

        assert request_id in bus._peer_review_requests
        assert isinstance(bus._peer_review_requests[request_id], asyncio.Future)

    @pytest.mark.asyncio
    async def test_post_called_with_peer_review_channel(self):
        """request_peer_review posts to the peer-review channel."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        bus.post = AsyncMock(return_value=MagicMock())

        await bus.request_peer_review("proj-1", "frontend-developer", "code-reviewer", "q")

        bus.post.assert_called_once()
        call_kwargs = bus.post.call_args
        assert call_kwargs.kwargs.get("channel") == "peer-review" or call_kwargs.args[1] == "peer-review"


class TestPostPeerReviewResponse:
    @pytest.mark.asyncio
    async def test_resolves_future(self):
        """post_peer_review_response resolves the pending Future."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        bus.post = AsyncMock(return_value=MagicMock())

        request_id = await bus.request_peer_review("p", "a1", "a2", "q")
        await bus.post_peer_review_response("p", request_id, "a2", "Looks good!")

        future = bus._peer_review_requests[request_id]
        assert future.done()
        assert future.result() == "Looks good!"

    @pytest.mark.asyncio
    async def test_no_error_on_unknown_request_id(self):
        """Responding to an unknown request_id does not raise."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        bus.post = AsyncMock(return_value=MagicMock())

        # Should not raise
        await bus.post_peer_review_response("p", "nonexistent-id", "a2", "response")


class TestWaitForPeerReview:
    @pytest.mark.asyncio
    async def test_returns_response_when_resolved(self):
        """wait_for_peer_review returns the response string when the future resolves."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        bus.post = AsyncMock(return_value=MagicMock())

        request_id = await bus.request_peer_review("p", "a1", "a2", "q")

        # Resolve concurrently
        async def resolve():
            await asyncio.sleep(0.01)
            await bus.post_peer_review_response("p", request_id, "a2", "LGTM")

        result, _ = await asyncio.gather(
            bus.wait_for_peer_review(request_id, timeout_seconds=5.0),
            resolve(),
        )

        assert result == "LGTM"

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        """wait_for_peer_review returns None when the timeout expires."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()
        bus.post = AsyncMock(return_value=MagicMock())

        request_id = await bus.request_peer_review("p", "a1", "a2", "q")

        result = await bus.wait_for_peer_review(request_id, timeout_seconds=0.05)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_request_id(self):
        """wait_for_peer_review returns None for an unknown request_id."""
        from src.communication.message_bus import MessageBus

        bus = MessageBus()

        result = await bus.wait_for_peer_review("no-such-id", timeout_seconds=0.05)

        assert result is None


# ── REST endpoint tests ───────────────────────────────────────────────────────
# Build a minimal FastAPI app that wires only the peer-review endpoints.
# This avoids importing src.main (which pulls in the full tool_executor
# singleton and all its heavy dependencies).


@pytest.fixture(scope="module")
def peer_review_app():
    """Minimal FastAPI app with only the peer-review endpoints under test."""
    from fastapi import FastAPI, HTTPException
    from src.communication.message_bus import MessageBus

    test_bus = MessageBus()
    mini_app = FastAPI()

    @mini_app.post("/api/projects/{project_id}/peer-review")
    async def _request_peer_review(project_id: str, body: dict):
        from_agent = body.get("from_agent")
        to_agent = body.get("to_agent")
        question = body.get("question")
        context = body.get("context", "")
        if not from_agent or not to_agent or not question:
            raise HTTPException(400, "from_agent, to_agent, and question are required")
        request_id = await test_bus.request_peer_review(
            project_id=project_id,
            from_agent=from_agent,
            to_agent=to_agent,
            question=question,
            context=context,
        )
        return {"request_id": request_id}

    @mini_app.post("/api/projects/{project_id}/peer-review/{request_id}/respond")
    async def _respond_peer_review(project_id: str, request_id: str, body: dict):
        from_agent = body.get("from_agent")
        response = body.get("response")
        if not from_agent or response is None:
            raise HTTPException(400, "from_agent and response are required")
        await test_bus.post_peer_review_response(
            project_id=project_id,
            request_id=request_id,
            from_agent=from_agent,
            response=response,
        )
        return {"status": "ok", "request_id": request_id}

    # Stub out DB-hitting post so tests don't need a real project in the DB
    test_bus.post = AsyncMock(return_value=MagicMock())

    # Attach bus so tests can inspect it
    mini_app.state.bus = test_bus
    return mini_app


class TestPeerReviewRestEndpoints:
    @pytest.mark.asyncio
    async def test_post_peer_review_returns_request_id(self, peer_review_app):
        """POST /api/projects/{id}/peer-review returns a request_id."""
        async with AsyncClient(
            transport=ASGITransport(app=peer_review_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/projects/proj-abc/peer-review",
                json={
                    "from_agent": "frontend-developer",
                    "to_agent": "code-reviewer",
                    "question": "Is this safe?",
                    "context": "line 42",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "request_id" in data
        assert isinstance(data["request_id"], str)
        assert len(data["request_id"]) > 0

    @pytest.mark.asyncio
    async def test_post_peer_review_missing_fields_returns_400(self, peer_review_app):
        """POST /api/projects/{id}/peer-review with missing fields returns 400."""
        async with AsyncClient(
            transport=ASGITransport(app=peer_review_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/projects/proj-abc/peer-review",
                json={"from_agent": "frontend-developer"},  # missing to_agent + question
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_post_peer_review_respond_returns_200(self, peer_review_app):
        """POST /api/projects/{id}/peer-review/{id}/respond returns 200 with status ok."""
        # First create a request so there's a valid pending future
        bus: MessageBus = peer_review_app.state.bus
        request_id = await bus.request_peer_review("proj-abc", "frontend-developer", "code-reviewer", "q")

        async with AsyncClient(
            transport=ASGITransport(app=peer_review_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/projects/proj-abc/peer-review/{request_id}/respond",
                json={
                    "from_agent": "code-reviewer",
                    "response": "Looks fine to me.",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
        assert data.get("request_id") == request_id

    @pytest.mark.asyncio
    async def test_post_peer_review_respond_missing_fields_returns_400(self, peer_review_app):
        """POST /api/projects/{id}/peer-review/{id}/respond with missing fields returns 400."""
        async with AsyncClient(
            transport=ASGITransport(app=peer_review_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/projects/proj-abc/peer-review/req-999/respond",
                json={"from_agent": "code-reviewer"},  # missing response
            )

        assert resp.status_code == 400
