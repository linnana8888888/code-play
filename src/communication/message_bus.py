"""Message Bus — project channels, @-mentions, and human escalation."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from src.models.messages import Message, EscalationRequest
from src.database import get_studio_db


class MessageBus:
    def __init__(self):
        # Subscribers: channel -> list of callbacks
        self._subscribers: dict[str, list[callable]] = {}
        # Mention watchers: agent_id -> callback
        self._mention_watchers: dict[str, callable] = {}
        # Pending escalations: escalation_id -> asyncio.Event
        self._pending_escalations: dict[int, asyncio.Event] = {}
        self._escalation_responses: dict[int, str] = {}
        # Peer review: request_id -> asyncio.Future
        self._peer_review_requests: dict[str, asyncio.Future] = {}
        # WebSocket broadcast callback (set by FastAPI)
        self._ws_broadcast: callable = None

    def set_ws_broadcast(self, callback: callable):
        """Set the WebSocket broadcast function (called by main.py)."""
        self._ws_broadcast = callback

    # --- Publishing ---

    async def post(
        self,
        project_id: str,
        channel: str,
        sender: str,
        content: str,
        mentions: list[str] = None,
    ) -> Message:
        """Post a message to a project channel."""
        mentions = mentions or []
        now = datetime.now(timezone.utc).isoformat()

        with get_studio_db() as db:
            cursor = db.execute(
                """INSERT INTO messages (project_id, channel, sender, content, mentions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, channel, sender, content, json.dumps(mentions), now),
            )
            msg_id = cursor.lastrowid

        message = Message(
            id=msg_id,
            project_id=project_id,
            channel=channel,
            sender=sender,
            content=content,
            mentions=mentions,
            created_at=datetime.fromisoformat(now),
        )

        # Notify channel subscribers
        key = f"{project_id}:{channel}"
        for callback in self._subscribers.get(key, []):
            try:
                await callback(message)
            except Exception:
                pass

        # Notify @-mentioned agents
        for agent_id in mentions:
            watcher = self._mention_watchers.get(agent_id)
            if watcher:
                try:
                    await watcher(message)
                except Exception:
                    pass

        # Broadcast to WebSocket for dashboard
        if self._ws_broadcast:
            try:
                await self._ws_broadcast({
                    "type": "message",
                    "data": {
                        "id": msg_id,
                        "project_id": project_id,
                        "channel": channel,
                        "sender": sender,
                        "content": content,
                        "mentions": mentions,
                        "created_at": now,
                    },
                })
            except Exception:
                pass

        return message

    # --- Reading ---

    def get_messages(
        self,
        project_id: str,
        channel: str = "general",
        limit: int = 50,
        since: datetime = None,
    ) -> list[Message]:
        """Read messages from a channel."""
        sql = "SELECT * FROM messages WHERE project_id = ? AND channel = ?"
        params = [project_id, channel]

        if since:
            sql += " AND created_at > ?"
            params.append(since.isoformat())

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_studio_db() as db:
            rows = db.execute(sql, params).fetchall()

        messages = []
        for r in reversed(rows):
            messages.append(Message(
                id=r["id"],
                project_id=r["project_id"],
                channel=r["channel"],
                sender=r["sender"],
                content=r["content"],
                mentions=json.loads(r["mentions"]) if r["mentions"] else [],
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None,
            ))
        return messages

    def get_mentions(self, agent_id: str, project_id: str = None, limit: int = 20) -> list[Message]:
        """Get messages that @-mention a specific agent."""
        sql = "SELECT * FROM messages WHERE mentions LIKE ?"
        params = [f'%"{agent_id}"%']

        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_studio_db() as db:
            rows = db.execute(sql, params).fetchall()

        return [
            Message(
                id=r["id"],
                project_id=r["project_id"],
                channel=r["channel"],
                sender=r["sender"],
                content=r["content"],
                mentions=json.loads(r["mentions"]) if r["mentions"] else [],
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None,
            )
            for r in reversed(rows)
        ]

    # --- Subscriptions ---

    def subscribe(self, project_id: str, channel: str, callback: callable):
        """Subscribe to messages on a channel."""
        key = f"{project_id}:{channel}"
        if key not in self._subscribers:
            self._subscribers[key] = []
        self._subscribers[key].append(callback)

    def unsubscribe(self, project_id: str, channel: str, callback: callable):
        """Unsubscribe from a channel."""
        key = f"{project_id}:{channel}"
        if key in self._subscribers:
            self._subscribers[key] = [c for c in self._subscribers[key] if c != callback]

    def watch_mentions(self, agent_id: str, callback: callable):
        """Watch for @-mentions of a specific agent."""
        self._mention_watchers[agent_id] = callback

    def unwatch_mentions(self, agent_id: str):
        """Stop watching mentions for an agent."""
        self._mention_watchers.pop(agent_id, None)

    # --- Escalation ---

    async def escalate(self, request: EscalationRequest) -> str | None:
        """Escalate a question to the human. Blocks until answered if blocking=True."""
        with get_studio_db() as db:
            cursor = db.execute(
                """INSERT INTO messages (project_id, channel, sender, content, mentions)
                   VALUES (?, 'escalation', ?, ?, '["human"]')""",
                (
                    request.project_id,
                    request.agent_instance_id,
                    json.dumps({
                        "question": request.question,
                        "options": request.options,
                        "context": request.context,
                    }),
                ),
            )
            esc_id = cursor.lastrowid

        # Broadcast escalation to WebSocket
        if self._ws_broadcast:
            try:
                await self._ws_broadcast({
                    "type": "escalation",
                    "data": {
                        "id": esc_id,
                        "project_id": request.project_id,
                        "agent_instance_id": request.agent_instance_id,
                        "question": request.question,
                        "options": request.options,
                        "context": request.context,
                    },
                })
            except Exception:
                pass

        if not request.blocking:
            return None

        # Block until human responds
        event = asyncio.Event()
        self._pending_escalations[esc_id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=600.0)  # 10 min
            return self._escalation_responses.get(esc_id, "")
        except asyncio.TimeoutError:
            return "[Escalation timed out after 10 minutes]"

    def resolve_escalation(self, escalation_id: int, response: str):
        """Human answers an escalation (called by dashboard API)."""
        self._escalation_responses[escalation_id] = response
        event = self._pending_escalations.pop(escalation_id, None)
        if event:
            event.set()

    # --- Channel listing ---

    def list_channels(self, project_id: str) -> list[str]:
        """List all channels that have messages for a project."""
        with get_studio_db() as db:
            rows = db.execute(
                "SELECT DISTINCT channel FROM messages WHERE project_id = ? ORDER BY channel",
                (project_id,),
            ).fetchall()
        return [r["channel"] for r in rows]

    # --- Agent-to-Agent Peer Review ---

    async def request_peer_review(
        self,
        project_id: str,
        from_agent: str,
        to_agent: str,
        question: str,
        context: str = "",
    ) -> str:
        """
        Send a direct review request from one agent to another.
        Posts a message to the project channel tagged for the target agent.
        Returns a request_id the caller can use to poll for the response.
        """
        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._peer_review_requests[request_id] = future

        content = json.dumps({
            "type": "peer_review_request",
            "request_id": request_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "question": question,
            "context": context,
        })
        await self.post(
            project_id=project_id,
            channel="peer-review",
            sender=from_agent,
            content=content,
            mentions=[to_agent],
        )
        return request_id

    async def post_peer_review_response(
        self,
        project_id: str,
        request_id: str,
        from_agent: str,
        response: str,
    ) -> None:
        """
        Post a response to a peer review request.
        Resolves the pending request_id.
        """
        content = json.dumps({
            "type": "peer_review_response",
            "request_id": request_id,
            "from_agent": from_agent,
            "response": response,
        })
        await self.post(
            project_id=project_id,
            channel="peer-review",
            sender=from_agent,
            content=content,
        )
        future = self._peer_review_requests.get(request_id)
        if future and not future.done():
            future.set_result(response)

    async def wait_for_peer_review(
        self,
        request_id: str,
        timeout_seconds: float = 30.0,
    ) -> str | None:
        """
        Wait for a peer review response.
        Returns the response string, or None on timeout.
        """
        future = self._peer_review_requests.get(request_id)
        if future is None:
            return None
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=timeout_seconds)
            return result
        except asyncio.TimeoutError:
            return None


# Singleton
message_bus = MessageBus()
