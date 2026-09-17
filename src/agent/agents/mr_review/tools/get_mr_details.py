"""Fetch merge request metadata (title, description, author, branches, commits)."""
from __future__ import annotations

import asyncio
from typing import Any

from agent.agents.mr_review.tools._base import GitLabTool
from agent.tools.schema import ToolParameter, ToolSchema


class GetMRDetailsTool(GitLabTool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="get_mr_details",
            description=(
                "Fetch merge request metadata: title, description, author, "
                "source/target branches, state, labels, and commit messages. "
                "Use this to understand the intent behind the changes."
            ),
            parameters=[
                ToolParameter(
                    name="project_id",
                    type="string",
                    description="Numeric project ID or URL-path 'group/project'.",
                ),
                ToolParameter(
                    name="mr_iid",
                    type="integer",
                    description="The merge request IID (project-scoped number).",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        project_id = kwargs["project_id"]
        mr_iid = int(kwargs["mr_iid"])
        mr = self.client.get_merge_request(project_id, mr_iid)

        lines = [
            f"Title: {mr.get('title', '')}",
            f"MR IID: !{mr.get('iid')}  (state: {mr.get('state')}, draft: {mr.get('draft', False)})",
            f"Author: {(mr.get('author') or {}).get('username', '?')}",
            f"Branches: {mr.get('source_branch')} -> {mr.get('target_branch')}",
            f"Labels: {', '.join(mr.get('labels', [])) or 'none'}",
            f"Web URL: {mr.get('web_url', '')}",
            "",
            "Description:",
            (mr.get('description') or "(no description)").strip(),
        ]

        try:
            commits = self.client.get_mr_commits(project_id, mr_iid)
            if commits:
                lines.append("")
                lines.append(f"Commits ({len(commits)}):")
                for c in commits[:30]:
                    lines.append(f"  - {c.get('short_id', '')} {c.get('title', '')}")
        except Exception as e:  # commits are best-effort context
            lines.append(f"\n(could not fetch commits: {e})")

        return "\n".join(lines)
