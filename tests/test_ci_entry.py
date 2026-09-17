"""CI entry mode-decision + get_branch_diff (offline, mocked client/env)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_ci_entry():
    spec = importlib.util.spec_from_file_location("ci_entry", ROOT / "ci_entry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ci = _load_ci_entry()


class _Cfg:
    class gitlab:
        base_url = "https://gl"
        token = "t"
        api_version = "v4"
        timeout_seconds = 30
        verify_ssl = False
        ca_bundle = ""
        ignore_paths = ["package-lock.json"]
        max_diff_chars = 60000


class _FakeClient:
    def __init__(self, open_mr=None, default="main"):
        self._open_mr = open_mr
        self._default = default

    def get_default_branch(self, project_id):
        return self._default

    def find_open_mr(self, project_id, source_branch, target_branch=None):
        return self._open_mr


def _set_ci_env(monkeypatch, **kv):
    # clear the ones we care about first
    for k in ["CI_PROJECT_ID", "CI_PIPELINE_SOURCE", "CI_MERGE_REQUEST_IID",
              "CI_DEFAULT_BRANCH", "CI_COMMIT_REF_NAME",
              "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"]:
        monkeypatch.delenv(k, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def test_mr_pipeline_mode(monkeypatch):
    _set_ci_env(monkeypatch, CI_PROJECT_ID="42",
                CI_PIPELINE_SOURCE="merge_request_event",
                CI_MERGE_REQUEST_IID="7", CI_DEFAULT_BRANCH="main",
                CI_MERGE_REQUEST_SOURCE_BRANCH_NAME="feat")
    monkeypatch.setattr(ci, "client_from_config", lambda cfg: _FakeClient(), raising=False)
    # client_from_config is imported inside _decide_target from agent.gitlab_client
    import agent.gitlab_client as glc
    monkeypatch.setattr(glc, "client_from_config", lambda cfg: _FakeClient())
    job = ci._decide_target(_Cfg())
    assert job["mode"] == "mr" and job["post"] is True and job["mr_iid"] == 7


def test_branch_with_existing_open_mr(monkeypatch):
    _set_ci_env(monkeypatch, CI_PROJECT_ID="42", CI_PIPELINE_SOURCE="push",
                CI_DEFAULT_BRANCH="main", CI_COMMIT_REF_NAME="feature/x")
    import agent.gitlab_client as glc
    monkeypatch.setattr(glc, "client_from_config",
                        lambda cfg: _FakeClient(open_mr={"iid": 12}))
    job = ci._decide_target(_Cfg())
    assert job["mode"] == "mr" and job["post"] is True and job["mr_iid"] == 12


def test_branch_without_mr_is_print_only(monkeypatch):
    _set_ci_env(monkeypatch, CI_PROJECT_ID="42", CI_PIPELINE_SOURCE="push",
                CI_DEFAULT_BRANCH="main", CI_COMMIT_REF_NAME="feature/x")
    import agent.gitlab_client as glc
    monkeypatch.setattr(glc, "client_from_config",
                        lambda cfg: _FakeClient(open_mr=None))
    job = ci._decide_target(_Cfg())
    assert job["mode"] == "branch" and job["post"] is False
    assert job["source_branch"] == "feature/x" and job["target_branch"] == "main"


def test_default_branch_is_none(monkeypatch):
    _set_ci_env(monkeypatch, CI_PROJECT_ID="42", CI_PIPELINE_SOURCE="push",
                CI_DEFAULT_BRANCH="main", CI_COMMIT_REF_NAME="main")
    import agent.gitlab_client as glc
    monkeypatch.setattr(glc, "client_from_config", lambda cfg: _FakeClient())
    job = ci._decide_target(_Cfg())
    assert job["mode"] == "none"


def test_prompt_branch_mode_forbids_mr_tools():
    p = ci._build_prompt({"mode": "branch", "project_id": "x",
                          "source_branch": "feat", "target_branch": "main"})
    assert "get_branch_diff" in p and "DO NOT call any MR tools" in p


def test_summary_posted_detection():
    from agent.core.context import ConversationContext
    from agent.core.types import Message, Role, ToolResult

    ctx = ConversationContext()
    assert ci._summary_posted(ctx) is False

    # a failed post does not count
    ctx.add(Message(role=Role.TOOL, tool_results=[
        ToolResult(tool_call_id="1", name="post_mr_comment", content="err", is_error=True)]))
    assert ci._summary_posted(ctx) is False

    # a successful post counts
    ctx.add(Message(role=Role.TOOL, tool_results=[
        ToolResult(tool_call_id="2", name="post_mr_comment", content="Posted (id=1).")]))
    assert ci._summary_posted(ctx) is True


# --- get_branch_diff tool ---
def test_get_branch_diff_formats_compare(monkeypatch):
    from agent.agents.mr_review.tools.get_branch_diff import GetBranchDiffTool

    class _C:
        def compare(self, project_id, from_ref, to_ref, straight=False):
            assert from_ref == "main" and to_ref == "feat"
            return {"diffs": [{"new_path": "a.py", "new_file": True, "diff": "+x"}]}

    t = GetBranchDiffTool(_Cfg())
    t._client = _C()
    import asyncio
    out = asyncio.get_event_loop().run_until_complete(
        t.execute(project_id="x", source_branch="feat", target_branch="main")
    )
    assert "a.py" in out and "new" in out and "```diff" in out
