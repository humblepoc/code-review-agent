"""Comment prefix applied to all posted MR comments."""
from agent.gitlab_client import COMMENT_PREFIX, _with_prefix


def test_prefix_is_ai_review_agent():
    assert COMMENT_PREFIX == "AI Review Agent:"


def test_prefix_prepended():
    out = _with_prefix("Looks good.")
    assert out == "AI Review Agent: Looks good."


def test_prefix_idempotent():
    once = _with_prefix("Fix this.")
    twice = _with_prefix(once)
    assert once == twice
    assert twice.count(COMMENT_PREFIX) == 1


def test_prefix_handles_leading_whitespace():
    out = _with_prefix("  already spaced")
    assert out.startswith("AI Review Agent:")


def test_prefix_empty_body():
    assert _with_prefix("").startswith("AI Review Agent:")
