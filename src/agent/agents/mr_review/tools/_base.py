"""Shared base for GitLab tools.

Note: this module name starts with ``_`` so the flavor loader skips it during
tool discovery (it defines a base class, not a usable tool).
"""
from __future__ import annotations

from agent.config import AgentConfig
from agent.gitlab_client import GitLabClient, client_from_config
from agent.tools.base import Tool


class GitLabTool(Tool):
    """Base class holding the AgentConfig and a lazily-built GitLab client."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._gitlab_cfg = config.gitlab
        self._client: GitLabClient | None = None

    @property
    def client(self) -> GitLabClient:
        if self._client is None:
            self._client = client_from_config(self._gitlab_cfg)
        return self._client


def format_diffs(diffs: list[dict], header_line: str, ignore: list[str], budget: int) -> str:
    """Format a list of GitLab diff dicts into a budget-capped Markdown string.

    Shared by get_mr_changes and get_branch_diff so both render diffs the same
    way. ``diffs`` is the list of per-file dicts from the MR ``/changes`` or the
    ``/compare`` endpoint (both use new_path/old_path/new_file/.../diff keys).
    """
    if not diffs:
        return "No file changes found."

    lines: list[str] = [header_line, ""]
    used = 0
    for ch in diffs:
        path = ch.get("new_path") or ch.get("old_path", "?")
        flags = []
        if ch.get("new_file"):
            flags.append("new")
        if ch.get("deleted_file"):
            flags.append("deleted")
        if ch.get("renamed_file"):
            flags.append(f"renamed from {ch.get('old_path')}")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        header = f"### {path}{flag_str}"

        if any(ig in f"/{path}" or ig == path for ig in ignore):
            lines.append(header)
            lines.append("(diff omitted — ignored path)")
            lines.append("")
            continue

        diff = ch.get("diff", "") or ""
        if used + len(diff) > budget:
            remaining = max(0, budget - used)
            diff = diff[:remaining] + "\n... [diff truncated to protect context budget] ..."
        used += len(diff)

        lines.append(header)
        lines.append("```diff")
        lines.append(diff.rstrip())
        lines.append("```")
        lines.append("")

        if used >= budget:
            lines.append(f"... [remaining files omitted; diff budget {budget} chars reached] ...")
            break

    return "\n".join(lines)
