"""Approve a merge request (guarded by config)."""
from __future__ import annotations

import asyncio
from typing import Any

from agent.agents.mr_review.tools._base import GitLabTool
from agent.tools.schema import ToolParameter, ToolSchema


class ApproveMRTool(GitLabTool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="approve_mr",
            description=(
                "Approve the merge request. Only call this when the review found "
                "no blocking issues. Approval is disabled by default and must be "
                "enabled via config (gitlab.approve=true); otherwise this is a no-op."
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
        if not self._gitlab_cfg.approve:
            return "[skipped] Auto-approval is disabled (gitlab.approve=false)."
        self.client.approve_mr(kwargs["project_id"], int(kwargs["mr_iid"]))
        return "Merge request approved."
