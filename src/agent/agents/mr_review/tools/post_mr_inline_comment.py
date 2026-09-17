"""Post an inline (line-anchored) review comment on a merge request diff."""
from __future__ import annotations

import asyncio
from typing import Any

from agent.agents.mr_review.tools._base import GitLabTool
from agent.tools.schema import ToolParameter, ToolSchema


class PostMRInlineCommentTool(GitLabTool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="post_mr_inline_comment",
            description=(
                "Post an inline comment anchored to a specific line in a changed "
                "file (creates a resolvable discussion). Use for concrete, "
                "line-level findings. The tool resolves the required diff SHAs "
                "automatically — you only supply the file path and the line. "
                "For a line in the NEW version of the file, set new_line; for a "
                "line only in the OLD version (e.g. commenting on deleted code), "
                "set old_line instead."
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
                    name="file_path",
                    type="string",
                    description="New file path the comment applies to (old_path if the file was deleted).",
                ),
                ToolParameter(
                    name="body",
                    type="string",
                    description="The comment body in GitLab Markdown.",
                ),
                ToolParameter(
                    name="new_line",
                    type="integer",
                    description="Line number in the new version of the file (1-based).",
                    required=False,
                ),
                ToolParameter(
                    name="old_line",
                    type="integer",
                    description="Line number in the old version of the file (1-based).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        if not self._gitlab_cfg.post_comments:
            return (
                "[skipped] Commenting is disabled (gitlab.post_comments=false). "
                f"Inline note NOT posted for {kwargs.get('file_path')}:"
                f"{kwargs.get('new_line') or kwargs.get('old_line')}. "
                "Include this finding in the summary instead."
            )

        project_id = kwargs["project_id"]
        mr_iid = int(kwargs["mr_iid"])
        new_line = kwargs.get("new_line")
        old_line = kwargs.get("old_line")
        if new_line is None and old_line is None:
            return "[error] Provide new_line (preferred) or old_line for the inline comment."

        mr = self.client.get_merge_request(project_id, mr_iid)
        diff_refs = mr.get("diff_refs") or {}
        base_sha = diff_refs.get("base_sha")
        head_sha = diff_refs.get("head_sha")
        start_sha = diff_refs.get("start_sha")
        if not (base_sha and head_sha and start_sha):
            return "[error] Could not resolve MR diff_refs; cannot anchor inline comment."

        position: dict[str, Any] = {
            "position_type": "text",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "start_sha": start_sha,
            "new_path": kwargs["file_path"],
            "old_path": kwargs["file_path"],
        }
        if new_line is not None:
            position["new_line"] = int(new_line)
        if old_line is not None:
            position["old_line"] = int(old_line)

        try:
            disc = self.client.create_mr_discussion(
                project_id, mr_iid, kwargs["body"], position=position
            )
            return f"Posted inline comment (discussion id={disc.get('id')})."
        except Exception as e:
            # Inline anchoring can fail if the line isn't part of the diff.
            # Fall back to a general note so the finding isn't lost.
            loc = kwargs["file_path"]
            loc += f":{new_line}" if new_line is not None else f" (old line {old_line})"
            body = f"**On `{loc}`:**\n\n{kwargs['body']}\n\n_(could not anchor inline: {e})_"
            note = self.client.create_mr_note(project_id, mr_iid, body)
            return f"Inline anchoring failed; posted as general note (id={note.get('id')})."
