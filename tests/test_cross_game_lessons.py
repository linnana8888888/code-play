"""Tests for CrossGameLessonStore (studio-wide cross-game lesson memory)."""
import pytest
from unittest.mock import patch
import sqlite3
from contextlib import contextmanager

# ---------------------------------------------------------------------------
# Fixtures: patch get_studio_db to use an in-memory SQLite DB so tests are
# fully isolated from the real studio.db on disk.
# ---------------------------------------------------------------------------

def _make_in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cross_game_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_role TEXT NOT NULL,
            category TEXT NOT NULL,
            lesson TEXT NOT NULL,
            source_project_id TEXT NOT NULL,
            source_cycle TEXT,
            confidence REAL DEFAULT 0.5,
            created_at TEXT NOT NULL,
            last_confirmed_at TEXT,
            confirmation_count INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_cgl_agent_role ON cross_game_lessons(agent_role);
        CREATE INDEX IF NOT EXISTS idx_cgl_category ON cross_game_lessons(category);
    """)
    conn.commit()
    return conn


@pytest.fixture
def store(monkeypatch):
    """Return a CrossGameLessonStore backed by an isolated in-memory DB."""
    db_conn = _make_in_memory_db()

    @contextmanager
    def fake_get_studio_db():
        try:
            yield db_conn
            db_conn.commit()
        except Exception:
            db_conn.rollback()
            raise

    import src.memory.agent_lessons as lessons_module
    monkeypatch.setattr(lessons_module, "get_studio_db", fake_get_studio_db)

    # Re-import to pick up the monkeypatched dependency
    from src.memory.agent_lessons import CrossGameLessonStore
    return CrossGameLessonStore()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAddLesson:
    def test_add_lesson_creates_with_default_confidence(self, store):
        lesson_id = store.add_lesson(
            agent_role="frontend-developer",
            category="three_js",
            lesson="Disable shadow maps by default on LEGO proxy",
            source_project_id="proj-001",
        )
        assert isinstance(lesson_id, int)
        assert lesson_id > 0

        lessons = store.get_lessons("frontend-developer")
        assert len(lessons) == 1
        assert lessons[0]["confidence"] == 0.5
        assert lessons[0]["confirmation_count"] == 1
        assert lessons[0]["category"] == "three_js"

    def test_add_lesson_identical_text_increments_count_not_duplicate(self, store):
        lesson_text = "Always call repo_file_list before repo_file_read"
        id1 = store.add_lesson(
            agent_role="tool-user",
            category="tool_use",
            lesson=lesson_text,
            source_project_id="proj-001",
        )
        id2 = store.add_lesson(
            agent_role="tool-user",
            category="tool_use",
            lesson=lesson_text,
            source_project_id="proj-002",
        )

        # Same id returned, no duplicate row
        assert id1 == id2

        lessons = store.get_all_lessons()
        assert len(lessons) == 1
        assert lessons[0]["confirmation_count"] == 2
        # Confidence should have increased
        assert lessons[0]["confidence"] > 0.5

    def test_add_lesson_case_insensitive_dedup(self, store):
        id1 = store.add_lesson(
            agent_role="game-designer",
            category="kid_safety",
            lesson="No blood or gore in any asset",
            source_project_id="proj-001",
        )
        id2 = store.add_lesson(
            agent_role="game-designer",
            category="kid_safety",
            lesson="  NO BLOOD OR GORE IN ANY ASSET  ",
            source_project_id="proj-002",
        )
        assert id1 == id2
        lessons = store.get_all_lessons()
        assert len(lessons) == 1


class TestGetLessons:
    def test_get_lessons_returns_top_n_by_confidence(self, store):
        # Add 4 lessons, manually set different confidences via confirm
        for i in range(4):
            store.add_lesson(
                agent_role="frontend-developer",
                category="general",
                lesson=f"Lesson number {i}",
                source_project_id="proj-001",
            )

        # Confirm lesson 0 twice to boost its confidence above others
        all_lessons = store.get_all_lessons()
        lesson_0_id = next(l["id"] for l in all_lessons if l["lesson"] == "Lesson number 0")
        store.confirm_lesson(lesson_0_id, "proj-002")
        store.confirm_lesson(lesson_0_id, "proj-003")

        top3 = store.get_lessons("frontend-developer", limit=3)
        assert len(top3) == 3
        # Highest confidence lesson should be first
        assert top3[0]["id"] == lesson_0_id

    def test_get_lessons_unknown_role_returns_empty(self, store):
        result = store.get_lessons("nonexistent-role")
        assert result == []

    def test_get_lessons_respects_limit(self, store):
        for i in range(5):
            store.add_lesson(
                agent_role="game-designer",
                category="general",
                lesson=f"Distinct lesson {i}",
                source_project_id="proj-001",
            )
        result = store.get_lessons("game-designer", limit=2)
        assert len(result) == 2


class TestConfirmLesson:
    def test_confirm_lesson_increases_confidence(self, store):
        lesson_id = store.add_lesson(
            agent_role="backend-developer",
            category="roblox",
            lesson="Always use server-authoritative state in Roblox",
            source_project_id="proj-001",
        )
        before = store.get_lessons("backend-developer")[0]["confidence"]
        store.confirm_lesson(lesson_id, "proj-002")
        after = store.get_lessons("backend-developer")[0]["confidence"]
        assert after > before

    def test_confirm_lesson_caps_at_1(self, store):
        lesson_id = store.add_lesson(
            agent_role="backend-developer",
            category="roblox",
            lesson="Use RemoteEvents for client-server communication",
            source_project_id="proj-001",
        )
        # Confirm 15 times — confidence must not exceed 1.0
        for i in range(15):
            store.confirm_lesson(lesson_id, f"proj-{i:03d}")
        final = store.get_lessons("backend-developer")[0]["confidence"]
        assert final <= 1.0

    def test_confirm_nonexistent_lesson_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.confirm_lesson(99999, "proj-001")


class TestFormatForContext:
    def test_format_returns_empty_string_when_no_lessons(self, store):
        result = store.format_for_context("unknown-role")
        assert result == ""

    def test_format_returns_block_with_lessons(self, store):
        store.add_lesson(
            agent_role="game-designer",
            category="three_js",
            lesson="Three.js shadow maps cause 401 on LEGO proxy — disable shadows by default",
            source_project_id="proj-001",
        )
        store.add_lesson(
            agent_role="game-designer",
            category="tool_use",
            lesson="Always call repo_file_list before repo_file_read",
            source_project_id="proj-001",
        )

        result = store.format_for_context("game-designer")
        assert "## Studio Lessons (learned from previous games)" in result
        assert "[three_js]" in result
        assert "[tool_use]" in result
        assert "Three.js shadow maps" in result
        assert "repo_file_list" in result

    def test_format_respects_limit(self, store):
        for i in range(5):
            store.add_lesson(
                agent_role="game-designer",
                category="general",
                lesson=f"Lesson {i} for limit test",
                source_project_id="proj-001",
            )
        result = store.format_for_context("game-designer", limit=2)
        # Header + 2 lesson lines = 3 lines total
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) == 3  # header + 2 lessons
