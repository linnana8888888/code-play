"""Execution Workspaces — isolate agents into separate working directories.

Uses git worktrees when the project is a git repo, plain directory copies otherwise.
Each agent instance gets its own workspace to prevent file conflicts.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.settings import settings


class WorkspaceManager:
    """Manage per-agent working directories."""

    def create(self, project_id: str, instance_id: str) -> Path:
        """Create an isolated workspace for an agent instance.

        Returns the workspace path. Uses git worktree if project is
        a git repo, otherwise copies the directory.
        """
        project_dir = Path(settings.projects_dir) / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        worktree_base = project_dir / "worktrees"
        worktree_base.mkdir(exist_ok=True)
        workspace_path = worktree_base / instance_id

        if self._is_git_repo(project_dir):
            return self._create_git_worktree(project_dir, workspace_path, instance_id)
        else:
            return self._create_copy(project_dir, workspace_path)

    def cleanup(self, project_id: str, instance_id: str):
        """Remove an agent's workspace after completion."""
        project_dir = Path(settings.projects_dir) / project_id
        workspace_path = project_dir / "worktrees" / instance_id

        if not workspace_path.exists():
            return

        if self._is_git_repo(project_dir):
            self._remove_git_worktree(project_dir, workspace_path)
        else:
            shutil.rmtree(workspace_path, ignore_errors=True)

    def get_workspace_path(self, project_id: str, instance_id: str) -> Path | None:
        """Get the workspace path if it exists."""
        workspace_path = Path(settings.projects_dir) / project_id / "worktrees" / instance_id
        if workspace_path.exists():
            return workspace_path
        return None

    def _is_git_repo(self, path: Path) -> bool:
        """Check if a directory is a git repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _create_git_worktree(
        self, project_dir: Path, workspace_path: Path, instance_id: str
    ) -> Path:
        """Create a git worktree for isolated work."""
        branch_name = f"agent/{instance_id}"
        abs_workspace = workspace_path.resolve()
        try:
            subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(abs_workspace)],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        except subprocess.CalledProcessError:
            # Fallback: if worktree creation fails, use a copy
            return self._create_copy(project_dir, workspace_path)
        return workspace_path

    def _remove_git_worktree(self, project_dir: Path, workspace_path: Path):
        """Remove a git worktree and its branch."""
        abs_workspace = workspace_path.resolve()
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(abs_workspace), "--force"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # Force cleanup
            shutil.rmtree(workspace_path, ignore_errors=True)
            try:
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=str(project_dir),
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                pass

    def _create_copy(self, project_dir: Path, workspace_path: Path) -> Path:
        """Fallback: create a plain directory copy."""
        if workspace_path.exists():
            return workspace_path

        workspace_path.mkdir(parents=True, exist_ok=True)

        # Copy project files (skip worktrees dir, .git, __pycache__)
        for item in project_dir.iterdir():
            if item.name in ("worktrees", ".git", "__pycache__", ".venv"):
                continue
            dst = workspace_path / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)

        return workspace_path


def list_project_files(root: Path, max_files: int = 100) -> str:
    """Produce an indented file-tree string for a project directory.

    Excludes .git, node_modules, __pycache__, .venv, telemetry/, and
    binary blobs. Returns a compact tree suitable for LLM context injection.
    """
    EXCLUDE = {".git", "node_modules", "__pycache__", ".venv", "telemetry", ".DS_Store"}
    BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp3", ".wav", ".ogg", ".woff", ".woff2", ".ttf"}

    if not root.is_dir():
        return f"(directory not found: {root})"

    lines: list[str] = []
    count = 0

    def _walk(directory: Path, prefix: str = "") -> None:
        nonlocal count
        if count >= max_files:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            if entry.name in EXCLUDE:
                continue
            if count >= max_files:
                lines.append(f"{prefix}... ({max_files} file limit reached)")
                return
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                _walk(entry, prefix + "  ")
            elif entry.suffix.lower() not in BINARY_SUFFIXES:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                if size < 1024:
                    size_str = f"{size}B"
                else:
                    size_str = f"{size / 1024:.1f}K"
                lines.append(f"{prefix}{entry.name}  ({size_str})")
                count += 1

    _walk(root)
    return "\n".join(lines) if lines else "(empty directory)"


# Singleton
workspace_manager = WorkspaceManager()
