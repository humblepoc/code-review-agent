"""Minimal GitLab REST API client (v4).

Shared helper used by the mr_review agent's tools. Uses httpx (already a
framework dependency). Authenticates with a Personal/Project Access Token
via the ``PRIVATE-TOKEN`` header.

Only the endpoints needed for MR review are implemented. All methods are
synchronous; tools wrap them with ``asyncio.to_thread`` so they don't block
the event loop.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)


class GitLabError(RuntimeError):
    """Raised when a GitLab API call fails."""


class GitLabClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        api_version: str = "v4",
        timeout_seconds: int = 30,
        verify_ssl: bool = True,
        ca_bundle: str = "",
    ) -> None:
        if not base_url:
            raise GitLabError("GitLab base_url is not configured (set GITLAB_URL).")
        if not token:
            raise GitLabError("GitLab token is not configured (set GITLAB_TOKEN).")
        self._api = f"{base_url.rstrip('/')}/api/{api_version}"
        # Prefer a CA bundle (verify against the internal CA) over disabling
        # verification entirely.
        verify: Any = ca_bundle if ca_bundle else verify_ssl
        self._client = httpx.Client(
            headers={"PRIVATE-TOKEN": token},
            timeout=timeout_seconds,
            verify=verify,
        )

    # -- low-level ---------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._api}{path}"
        resp = self._client.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise GitLabError(
                f"GitLab {method} {path} -> {resp.status_code}: {resp.text[:500]}"
            )
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json: Optional[dict] = None) -> Any:
        return self._request("POST", path, json=json)

    def _get_paginated(self, path: str, params: Optional[dict] = None) -> list[Any]:
        """Fetch all pages of a list endpoint."""
        params = dict(params or {})
        params.setdefault("per_page", 100)
        page = 1
        items: list[Any] = []
        while True:
            params["page"] = page
            batch = self._get(path, params=params)
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            if len(batch) < params["per_page"]:
                break
            page += 1
        return items

    @staticmethod
    def _pid(project_id: str | int) -> str:
        """URL-encode a project id or full path (group/subgroup/project)."""
        return quote(str(project_id), safe="")

    # -- merge requests ----------------------------------------------------
    def get_merge_request(self, project_id: str | int, mr_iid: int) -> dict:
        return self._get(f"/projects/{self._pid(project_id)}/merge_requests/{mr_iid}")

    def get_mr_changes(self, project_id: str | int, mr_iid: int) -> dict:
        return self._get(
            f"/projects/{self._pid(project_id)}/merge_requests/{mr_iid}/changes"
        )

    def get_mr_commits(self, project_id: str | int, mr_iid: int) -> list[dict]:
        return self._get_paginated(
            f"/projects/{self._pid(project_id)}/merge_requests/{mr_iid}/commits"
        )

    def get_mr_versions(self, project_id: str | int, mr_iid: int) -> list[dict]:
        """MR diff versions — needed for base/head/start SHAs for inline notes."""
        return self._get(
            f"/projects/{self._pid(project_id)}/merge_requests/{mr_iid}/versions"
        )

    def list_merge_requests(
        self,
        project_id: str | int,
        source_branch: str | None = None,
        target_branch: str | None = None,
        state: str = "opened",
    ) -> list[dict]:
        """List merge requests for a project, optionally filtered by branches/state."""
        params: dict[str, Any] = {"state": state}
        if source_branch:
            params["source_branch"] = source_branch
        if target_branch:
            params["target_branch"] = target_branch
        return self._get_paginated(
            f"/projects/{self._pid(project_id)}/merge_requests", params=params
        )

    def find_open_mr(
        self,
        project_id: str | int,
        source_branch: str,
        target_branch: str | None = None,
    ) -> dict | None:
        """Return the first open MR for source->target, or None if none exist."""
        mrs = self.list_merge_requests(
            project_id, source_branch=source_branch, target_branch=target_branch, state="opened"
        )
        return mrs[0] if mrs else None

    def compare(
        self, project_id: str | int, from_ref: str, to_ref: str, straight: bool = False
    ) -> dict:
        """Compare two refs. Returns diffs of ``to_ref`` relative to ``from_ref``.

        With ``straight=False`` (default) GitLab compares using the merge-base
        of the two refs (``from...to``), which matches what an MR would show for
        a feature branch against the default branch.
        """
        return self._get(
            f"/projects/{self._pid(project_id)}/repository/compare",
            params={"from": from_ref, "to": to_ref, "straight": str(straight).lower()},
        )

    def get_default_branch(self, project_id: str | int) -> str:
        """Return the project's default branch name."""
        proj = self._get(f"/projects/{self._pid(project_id)}")
        return proj.get("default_branch", "main")

    # -- files -------------------------------------------------------------
    def get_file(self, project_id: str | int, file_path: str, ref: str) -> str:
        """Raw file content at a ref."""
        return self._get(
            f"/projects/{self._pid(project_id)}/repository/files/"
            f"{quote(file_path, safe='')}/raw",
            params={"ref": ref},
        )

    # -- notes / discussions ----------------------------------------------
    def create_mr_note(self, project_id: str | int, mr_iid: int, body: str) -> dict:
        """Post a general (non-inline) comment on the MR."""
        return self._post(
            f"/projects/{self._pid(project_id)}/merge_requests/{mr_iid}/notes",
            json={"body": body},
        )

    def create_mr_discussion(
        self,
        project_id: str | int,
        mr_iid: int,
        body: str,
        position: Optional[dict] = None,
    ) -> dict:
        """Create a discussion, optionally anchored to a line (inline comment)."""
        payload: dict[str, Any] = {"body": body}
        if position:
            payload["position"] = position
        return self._post(
            f"/projects/{self._pid(project_id)}/merge_requests/{mr_iid}/discussions",
            json=payload,
        )

    def approve_mr(self, project_id: str | int, mr_iid: int) -> dict:
        return self._post(
            f"/projects/{self._pid(project_id)}/merge_requests/{mr_iid}/approve"
        )

    def close(self) -> None:
        self._client.close()


def client_from_config(gitlab_cfg: Any) -> GitLabClient:
    """Build a GitLabClient from an AgentConfig.gitlab section."""
    return GitLabClient(
        base_url=gitlab_cfg.base_url,
        token=gitlab_cfg.token,
        api_version=gitlab_cfg.api_version,
        timeout_seconds=gitlab_cfg.timeout_seconds,
        verify_ssl=gitlab_cfg.verify_ssl,
        ca_bundle=getattr(gitlab_cfg, "ca_bundle", ""),
    )
