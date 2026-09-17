"""Post a general (summary) review comment on the merge request."""
from __future__ import annotations

import asyncio
from typing import Any

from agent.agents.mr_review.tools._base import GitLabTool
from agent.tools.schema import ToolParameter, ToolSchema


class PostMRCommentTool(GitLabTool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="post_mr_comment",
            description=(
                "Post a general (non-inline) comment on the merge request — use "
                "this for the overall review summary. Body supports GitLab "
                "Markdown. Posting can be disabled via config (post_comments), in "
                "which case this returns a notice instead of posting."
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
                ToolParameter(
                    name="body",
                    type="string",
                    description="The comment body in GitLab Markdown.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        if not self._gitlab_cfg.post_comments:
            return (
                "[skipped] Commenting is disabled (gitlab.post_comments=false). "
                "Review summary was NOT posted. Returning it to the caller instead:\n\n"
                + kwargs.get("body", "")
            )
        note = self.client.create_mr_note(
            kwargs["project_id"], int(kwargs["mr_iid"]), kwargs["body"]
        )
        return f"Posted review comment (note id={note.get('id')})."
