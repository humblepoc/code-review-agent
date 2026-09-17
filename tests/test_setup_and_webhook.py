"""Built-in opt-in (no bash for mr_review) + webhook verification + parsing."""
import json

from agent.config import AgentConfig
from agent.setup import build_registry, get_flavor
from agent import lambda_handler as lh


def _cfg(**gl):
    c = AgentConfig(flavor="mr_review")
    for k, v in gl.items():
        setattr(c.gitlab, k, v)
    c.gitlab.base_url = c.gitlab.base_url or "https://gl"
    c.gitlab.token = c.gitlab.token or "tok"
    return c


def test_mr_review_has_no_bash():
    cfg = _cfg()
    names = {t.name for t in build_registry(cfg, get_flavor(cfg)).list()}
    assert "bash" not in names
    # all the review tools are present
    for n in ["get_mr_details", "get_mr_changes", "get_file_content",
              "post_mr_comment", "post_mr_inline_comment", "approve_mr"]:
        assert n in names


def test_webhook_skipped_when_no_secret(monkeypatch):
    monkeypatch.delenv("GITLAB_WEBHOOK_SECRET", raising=False)
    # No secret configured anywhere -> verification passes.
    ok, _ = lh._verify_webhook({"headers": {}})
    assert ok is True


def test_webhook_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "s3cret")
    ok, reason = lh._verify_webhook({"headers": {"X-Gitlab-Token": "wrong"}})
    assert ok is False


def test_webhook_accepts_good_token(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "s3cret")
    ok, _ = lh._verify_webhook({"headers": {"x-gitlab-token": "s3cret"}})  # case-insensitive
    assert ok is True


def test_handler_returns_401_on_bad_token(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "s3cret")
    event = {
        "headers": {"X-Gitlab-Token": "nope"},
        "body": json.dumps({"object_kind": "merge_request",
                            "project": {"id": 1},
                            "object_attributes": {"iid": 2, "action": "open", "state": "opened"}}),
    }
    resp = lh.lambda_handler(event)
    assert resp["statusCode"] == 401


def test_parse_and_should_review(monkeypatch):
    payload = {
        "object_kind": "merge_request",
        "project": {"id": 42, "path_with_namespace": "g/p"},
        "object_attributes": {"iid": 7, "action": "open", "state": "opened", "draft": False},
        "user": {"username": "u"},
    }
    parsed = lh._parse_gitlab_mr(payload)
    assert parsed["project_id"] == 42 and parsed["mr_iid"] == 7
    assert lh._should_review(parsed) is True
    # draft is skipped
    parsed["draft"] = True
    assert lh._should_review(parsed) is False
