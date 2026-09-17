"""Fetch the diff/changes of a merge request."""
from __future__ import annotations

import asyncio
from typing import Any

from agent.agents.mr_review.tools._base import GitLabTool
from agent.tools.schema import ToolParameter, ToolSchema


class GetMRChangesTool(GitLabTool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="get_mr_changes",
            description=(
                "Fetch the file changes (unified diffs) for a merge request. "
                "This is the primary input for the review — call it first. "
                "Returns per-file diffs with new/deleted/renamed flags. Large "
                "diffs and ignored paths (lockfiles, vendored code) are trimmed."
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
        from agent.agents.mr_review.tools._base import format_diffs

        project_id = kwargs["project_id"]
        mr_iid = int(kwargs["mr_iid"])
        data = self.client.get_mr_changes(project_id, mr_iid)
        changes = data.get("changes", [])
        header = (
            f"MR !{mr_iid} — {len(changes)} changed file(s)\n"
            f"Source: {data.get('source_branch')} -> Target: {data.get('target_branch')}"
        )
        return format_diffs(
            changes, header, self._gitlab_cfg.ignore_paths, self._gitlab_cfg.max_diff_chars
        )
