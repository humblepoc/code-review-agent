"""get_file_content: ref defaulting + 404 recovery message."""
import pytest

from agent.agents.mr_review.tools.get_file_content import GetFileContentTool
from agent.gitlab_client import GitLabError


class _FakeConfig:
    class gitlab:  # noqa: N801 - simple stand-in
        base_url = "https://gl"
        token = "t"
        api_version = "v4"
        timeout_seconds = 30
        verify_ssl = False
        ca_bundle = ""


class _FakeClient:
    def __init__(self):
        self.calls = []

    def get_merge_request(self, project_id, mr_iid):
        return {"source_branch": "feature/x"}

    def get_mr_changes(self, project_id, mr_iid):
        return {"changes": [
            {"new_path": "src/app/main.py"},
            {"new_path": "src/app/utils/helper.py"},
        ]}

    def get_file(self, project_id, file_path, ref):
        self.calls.append((file_path, ref))
        if file_path == "src/app/main.py":
            return "print('hi')\n"
        raise GitLabError("GitLab GET ... -> 404: File Not Found")


def _tool():
    t = GetFileContentTool(_FakeConfig())
    t._client = _FakeClient()
    return t


async def test_ref_defaults_to_source_branch():
    t = _tool()
    out = await t.execute(project_id="x/y", file_path="src/app/main.py", mr_iid=7)
    assert "print('hi')" in out
    assert t._client.calls[-1] == ("src/app/main.py", "feature/x")


async def test_missing_ref_and_no_mr_iid_errors():
    t = _tool()
    out = await t.execute(project_id="x/y", file_path="src/app/main.py")
    assert "[error]" in out and "mr_iid" in out


async def test_404_returns_valid_paths_and_did_you_mean():
    t = _tool()
    out = await t.execute(project_id="x/y", file_path="src/wrong/helper.py", mr_iid=7)
    assert "[not found]" in out
    assert "src/app/utils/helper.py" in out          # listed as valid
    assert "Did you mean: src/app/utils/helper.py?" in out  # basename match
