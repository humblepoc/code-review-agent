"""Fetch full file content at a ref — for context beyond the diff hunks."""
from __future__ import annotations

import asyncio
from typing import Any

from agent.agents.mr_review.tools._base import GitLabTool
from agent.gitlab_client import GitLabError
from agent.tools.schema import ToolParameter, ToolSchema

MAX_FILE_CHARS = 20_000


class GetFileContentTool(GitLabTool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="get_file_content",
            description=(
                "Fetch the full content of a file at a git ref, for context beyond "
                "the diff hunks (e.g. a function's full body). Only request paths "
                "that appear in get_mr_changes. If you provide mr_iid, you can omit "
                "ref and it defaults to the MR source branch — this is the "
                "recommended usage. On a missing file the tool returns the valid "
                "changed paths so you can retry with the correct one."
            ),
            parameters=[
                ToolParameter(
                    name="project_id",
                    type="string",
                    description="Numeric project ID or URL-path 'group/project'.",
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Repository-relative file path exactly as shown in get_mr_changes.",
                ),
                ToolParameter(
                    name="mr_iid",
                    type="integer",
                    description="MR IID. Provide this to default ref to the MR source branch and enable path suggestions.",
                    required=False,
                ),
                ToolParameter(
                    name="ref",
                    type="string",
                    description="Branch or commit SHA. Optional if mr_iid is given (defaults to MR source branch).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        project_id = kwargs["project_id"]
        file_path = kwargs["file_path"]
        ref = kwargs.get("ref")
        mr_iid = kwargs.get("mr_iid")

        # Resolve a ref from the MR source branch if none was given.
        if not ref:
            if mr_iid is None:
                return (
                    "[error] No ref provided and no mr_iid to resolve one. "
                    "Either pass ref, or pass mr_iid to default to the MR source branch."
                )
            mr = self.client.get_merge_request(project_id, int(mr_iid))
            ref = mr.get("source_branch")
            if not ref:
                return "[error] Could not resolve the MR source branch; pass an explicit ref."

        try:
            content = self.client.get_file(project_id, file_path, ref)
        except GitLabError as e:
            if "404" in str(e):
                return self._not_found_message(project_id, mr_iid, file_path)
            raise

        if not isinstance(content, str):
            content = str(content)
        if len(content) > MAX_FILE_CHARS:
            content = content[:MAX_FILE_CHARS] + "\n... [file truncated] ..."
        return content

    def _not_found_message(self, project_id: str, mr_iid: Any, file_path: str) -> str:
        """On 404, list the actual changed paths so the model can retry correctly."""
        suggestion = ""
        if mr_iid is not None:
            try:
                changes = self.client.get_mr_changes(project_id, int(mr_iid)).get("changes", [])
                paths = [c.get("new_path") or c.get("old_path") for c in changes]
                paths = [p for p in paths if p]
                if paths:
                    # Highlight a likely match by basename.
                    base = file_path.rsplit("/", 1)[-1]
                    near = [p for p in paths if p.rsplit("/", 1)[-1] == base]
                    hint = f" Did you mean: {near[0]}?" if near else ""
                    suggestion = (
                        f"{hint} Valid changed paths in this MR:\n  - "
                        + "\n  - ".join(paths)
                    )
            except Exception:
                pass
        return (
            f"[not found] '{file_path}' does not exist at that ref."
            + (suggestion or " Use exactly the path shown in get_mr_changes.")
        )
