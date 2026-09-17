"""Diff a branch against a target (default) branch — for the no-MR case.

Used in CI when a feature branch has no open MR yet: we still want to review
what *would* be merged into the default branch. Uses GitLab's compare API so
the diff is computed relative to the merge-base (same as an MR would show).
"""
from __future__ import annotations

import asyncio
from typing import Any

from agent.agents.mr_review.tools._base import GitLabTool, format_diffs
from agent.tools.schema import ToolParameter, ToolSchema


class GetBranchDiffTool(GitLabTool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="get_branch_diff",
            description=(
                "Compare a source branch against a target branch (usually the "
                "default branch) and return the unified diffs — i.e. what would be "
                "merged. Use this when reviewing a branch that has no open merge "
                "request yet. Returns per-file diffs, budget-capped."
            ),
            parameters=[
                ToolParameter(
                    name="project_id",
                    type="string",
                    description="Numeric project ID or URL-path 'group/project'.",
                ),
                ToolParameter(
                    name="source_branch",
                    type="string",
                    description="The feature branch being reviewed.",
                ),
                ToolParameter(
                    name="target_branch",
                    type="string",
                    description="The branch it would merge into (usually the default branch).",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        project_id = kwargs["project_id"]
        source = kwargs["source_branch"]
        target = kwargs["target_branch"]
        # Compare target...source (diffs of source relative to the merge-base).
        data = self.client.compare(project_id, from_ref=target, to_ref=source)
        diffs = data.get("diffs", [])
        header = (
            f"Branch diff — {len(diffs)} changed file(s)\n"
            f"Source: {source} -> Target: {target} (no open MR; comparing against default branch)"
        )
        return format_diffs(
            diffs, header, self._gitlab_cfg.ignore_paths, self._gitlab_cfg.max_diff_chars
        )
