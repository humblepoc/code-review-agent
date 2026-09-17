"""AWS Lambda entry point — GitLab Merge Request review webhook.

Wiring:
  GitLab (project webhook: "Merge request events")
        -> API Gateway
        -> this Lambda

On each relevant MR event the handler parses the payload, builds a review
prompt, and runs the ``mr_review`` agent, whose tools call back to the GitLab
API to fetch diffs and post the review.

Supported invocation shapes:
  1. API Gateway proxy:   {"body": "<gitlab webhook json>", "headers": {...}}
  2. Direct GitLab JSON:  {"object_kind": "merge_request", ...}
  3. SQS event source:    {"Records": [{"eventSource": "aws:sqs", "body": ...}]}
  4. Manual/test invoke:  {"query": "review project 42 MR 7"}

The handler returns 200 for ignored/irrelevant events so GitLab does not
disable the webhook on non-actionable hooks.

To review a *different* kind of thing you never touch this file — you change
the agent directory (instructions.md + tools/).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# MR actions worth reviewing. "open"/"reopen" always; "update" only when the
# diff changed (new commits) — handled in _should_review.
_REVIEW_ACTIONS = {"open", "reopen", "update"}


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        force=True,
    )

    try:
        # SQS event source mapping: each record body is a webhook payload.
        records = event.get("Records")
        if records and any(r.get("eventSource") == "aws:sqs" for r in records):
            return _handle_sqs(records)

        payload = _parse_body(event)

        # Manual/test path: a raw query.
        if "query" in payload and "object_kind" not in payload:
            result = _run_sync(payload["query"], payload.get("config_overrides", {}))
            return _response(200, result)

        # Verify the GitLab webhook secret (X-Gitlab-Token) before doing any
        # work. Skipped only if no secret is configured (local/manual runs).
        ok, reason = _verify_webhook(event)
        if not ok:
            log.warning("Rejected webhook: %s", reason)
            return _response(401, {"status": "unauthorized", "reason": reason})

        parsed = _parse_gitlab_mr(payload)
        if parsed is None:
            log.info("Ignoring non-MR or unparseable event (object_kind=%s)",
                     payload.get("object_kind"))
            return _response(200, {"status": "ignored", "reason": "not a reviewable MR event"})

        if not _should_review(parsed):
            log.info("Skipping MR !%s action=%s", parsed["mr_iid"], parsed["action"])
            return _response(200, {"status": "skipped", "action": parsed["action"]})

        log.info("Reviewing MR !%s in project %s (action=%s)",
                 parsed["mr_iid"], parsed["project_id"], parsed["action"])
        prompt = _build_review_prompt(parsed)
        result = _run_sync(prompt, {})
        return _response(200, {"status": "reviewed", "mr_iid": parsed["mr_iid"], **result})

    except Exception as e:
        log.exception("Lambda handler error")
        # Still 200 so GitLab doesn't disable the webhook on transient errors.
        return _response(200, {"status": "error", "error": f"{type(e).__name__}: {e}"})


def _handle_sqs(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Process SQS records — each body is a GitLab webhook payload."""
    for record in records:
        if record.get("eventSource") != "aws:sqs":
            continue
        try:
            payload = json.loads(record.get("body", "{}"))
        except (json.JSONDecodeError, TypeError):
            log.exception("Failed to parse SQS record body; skipping")
            continue
        parsed = _parse_gitlab_mr(payload)
        if parsed is None or not _should_review(parsed):
            continue
        _run_sync(_build_review_prompt(parsed), {})
    return {}


# ---------------------------------------------------------------------------
# Webhook authentication
# ---------------------------------------------------------------------------
def _header(event: dict[str, Any], name: str) -> str | None:
    """Case-insensitive header lookup from an API Gateway event."""
    headers = event.get("headers") or {}
    target = name.lower()
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == target:
            return v
    return None


def _verify_webhook(event: dict[str, Any]) -> tuple[bool, str]:
    """Verify the GitLab webhook secret token.

    Returns (ok, reason). If no ``gitlab.webhook_secret`` is configured,
    verification is skipped (returns ok=True) so local/manual invocations still
    work. When a secret IS configured, the request must present a matching
    ``X-Gitlab-Token`` header.
    """
    import hmac

    from agent.config import load_config

    try:
        secret = load_config().gitlab.webhook_secret
    except Exception:
        secret = ""

    if not secret:
        return True, "no webhook secret configured (verification skipped)"

    provided = _header(event, "X-Gitlab-Token") or ""
    if hmac.compare_digest(provided, secret):
        return True, "ok"
    return False, "invalid or missing X-Gitlab-Token"


# ---------------------------------------------------------------------------
# GitLab webhook parsing
# ---------------------------------------------------------------------------
def _parse_gitlab_mr(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the fields we need from a GitLab merge_request webhook.

    Reference payload shape:
        {
          "object_kind": "merge_request",
          "project": {"id": 42, "path_with_namespace": "group/app", "web_url": ...},
          "object_attributes": {
              "iid": 7, "action": "open", "title": ..., "description": ...,
              "source_branch": ..., "target_branch": ..., "state": "opened",
              "last_commit": {"id": "..."}, "oldrev": "...", "url": ...
          },
          "user": {"username": ...}
        }
    """
    if payload.get("object_kind") != "merge_request":
        return None

    project = payload.get("project") or {}
    attrs = payload.get("object_attributes") or {}
    if not attrs:
        return None

    # Prefer numeric project id; fall back to path (client URL-encodes either).
    project_id = project.get("id")
    if project_id is None:
        project_id = project.get("path_with_namespace")
    mr_iid = attrs.get("iid")
    if project_id is None or mr_iid is None:
        return None

    return {
        "project_id": project_id,
        "project_path": project.get("path_with_namespace", ""),
        "mr_iid": mr_iid,
        "action": attrs.get("action", ""),
        "state": attrs.get("state", ""),
        "title": attrs.get("title", ""),
        "description": attrs.get("description", ""),
        "source_branch": attrs.get("source_branch", ""),
        "target_branch": attrs.get("target_branch", ""),
        "draft": attrs.get("draft", attrs.get("work_in_progress", False)),
        "author": (payload.get("user") or {}).get("username", ""),
        "web_url": attrs.get("url", project.get("web_url", "")),
        "oldrev": attrs.get("oldrev"),  # present on "update" only when commits changed
    }


def _should_review(parsed: dict[str, Any]) -> bool:
    action = parsed.get("action", "")
    if action not in _REVIEW_ACTIONS:
        return False
    # Skip drafts/WIP.
    if parsed.get("draft"):
        return False
    # Only review "update" when the code actually changed (new commits => oldrev set).
    if action == "update" and not parsed.get("oldrev"):
        return False
    # Only review open MRs.
    if parsed.get("state") and parsed["state"] not in ("opened", "reopened"):
        return False
    return True


def _build_review_prompt(parsed: dict[str, Any]) -> str:
    return (
        "A GitLab merge request needs review.\n\n"
        f"project_id: {parsed['project_id']}\n"
        f"mr_iid: {parsed['mr_iid']}\n"
        f"title: {parsed['title']}\n"
        f"author: {parsed['author']}\n"
        f"branches: {parsed['source_branch']} -> {parsed['target_branch']}\n"
        f"web_url: {parsed['web_url']}\n\n"
        "Review this merge request following your instructions. Use "
        "get_mr_details and get_mr_changes to gather the changes, leave inline "
        "comments for concrete findings, and post an overall summary comment. "
        "Pass the exact project_id and mr_iid values above to every tool."
    )


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------
def _run_sync(query: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """Run the async agent on a fresh event loop (Lambda-safe)."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_run(query, overrides))
    finally:
        loop.close()


async def _run(query: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """Load config, build the agent, run the loop, return structured results."""
    from agent.config import apply_provider_defaults, load_config
    from agent.core.context import ConversationContext
    from agent.core.loop import run_agent
    from agent.core.types import Message, Role
    from agent.llm.registry import get_provider
    from agent.setup import build_registry, get_flavor, get_system_prompt

    cfg = load_config()

    if v := overrides.get("provider"):
        cfg.llm.provider = v
    if v := overrides.get("model"):
        cfg.llm.model = v
    if v := overrides.get("flavor"):
        cfg.flavor = v
    apply_provider_defaults(cfg.llm)

    provider = get_provider(cfg.llm.provider, cfg)
    flavor = get_flavor(cfg)
    registry = build_registry(cfg, flavor)
    context = ConversationContext(system_prompt=get_system_prompt(cfg, flavor))
    context.add(Message(role=Role.USER, content=query))

    log.info(
        "Running agent '%s' (provider=%s model=%s max_iterations=%d)",
        cfg.flavor, cfg.llm.provider, cfg.llm.model, cfg.max_iterations,
    )
    result = await run_agent(provider, registry, context, max_iterations=cfg.max_iterations)

    return {
        "answer": result.content or "",
        "agent": cfg.flavor,
        "provider": cfg.llm.provider,
        "model": cfg.llm.model,
        "tokens": context.estimate_tokens(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)
    return body


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
