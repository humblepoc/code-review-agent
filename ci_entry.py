"""GitLab CI entry point — run the MR review agent inside a pipeline.

This is an alternative to the Lambda entry point (which is kept for later
VPC-based webhook deployment). Running in CI works today because the GitLab
runner is already inside the network that can reach the internal GitLab, and
it can reach the public Siemens AI gateway outbound.

Mode detection (from GitLab predefined CI variables):

  1. Merge-request pipeline (CI_PIPELINE_SOURCE == "merge_request_event"):
     review CI_MERGE_REQUEST_IID and POST comments to that MR.

  2. Branch pipeline (a push to a feature branch, no MR IID):
     - Look up an OPEN MR for source=current branch -> target=default branch.
     - If one exists: review that MR and POST comments to it.
     - If none exists: compare the branch against the default branch and PRINT
       the review to the job log only (no MR to comment on).

Required CI/CD variables:
  * AGENT_SIEMENS_API_KEY  — Siemens AI gateway key (SIAK-...)
  * GITLAB_TOKEN           — a token with 'api' scope (project/group access
                             token or a PAT). CI_JOB_TOKEN is NOT enough to
                             post notes, so provide GITLAB_TOKEN explicitly.

GitLab provides the rest (CI_API_V4_URL, CI_PROJECT_ID, CI_COMMIT_REF_NAME,
CI_DEFAULT_BRANCH, CI_MERGE_REQUEST_IID, CI_PIPELINE_SOURCE, ...).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Make the package importable whether run as a module or a script.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

log = logging.getLogger("ci_entry")

# Technical loggers whose INFO chatter (tool calls, HTTP requests, iterations)
# is only shown in verbose mode.
_TECHNICAL_LOGGERS = ("agent.core.loop", "agent.gitlab_client", "agent.llm", "httpx")


def _is_verbose() -> bool:
    """Verbose mode via --verbose/-v flag or AGENT_VERBOSE/AGENT_DEBUG env."""
    if any(a in ("--verbose", "-v", "--debug") for a in sys.argv[1:]):
        return True
    val = os.environ.get("AGENT_VERBOSE") or os.environ.get("AGENT_DEBUG") or ""
    return val.strip().lower() in ("1", "true", "yes", "on")


def _setup_logging(verbose: bool) -> None:
    """Configure logging.

    Verbose: full technical logs (tool calls, HTTP, iterations) at INFO — the
    original behavior.

    Default (non-verbose): technical loggers are quieted to WARNING so ERRORs
    and WARNINGs still surface, while ci_entry prints friendly progress lines.
    """
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        force=True,
    )
    if not verbose:
        for name in _TECHNICAL_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
    # ci_entry's own logger stays at INFO so our friendly/error lines show.
    log.setLevel(logging.INFO)


def _say(message: str) -> None:
    """Print a friendly, non-technical progress line (always shown)."""
    print(f"• {message}")


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def _gitlab_base_url() -> str:
    """Derive the GitLab base URL from CI_API_V4_URL or CI_SERVER_URL."""
    if url := os.environ.get("GITLAB_URL"):
        return url.rstrip("/")
    if server := os.environ.get("CI_SERVER_URL"):
        return server.rstrip("/")
    api = os.environ.get("CI_API_V4_URL", "")  # e.g. https://gitlab.ex.com/api/v4
    if api.endswith("/api/v4"):
        return api[: -len("/api/v4")]
    return api.rstrip("/")


def _decide_target(cfg) -> dict:
    """Resolve what to review from CI env vars. Returns a dict describing the job."""
    from agent.gitlab_client import client_from_config

    project_id = _env("CI_PROJECT_ID")
    if not project_id:
        raise SystemExit("CI_PROJECT_ID is not set — are we running in GitLab CI?")

    pipeline_source = _env("CI_PIPELINE_SOURCE")
    mr_iid = _env("CI_MERGE_REQUEST_IID")
    default_branch = _env("CI_DEFAULT_BRANCH", default="")
    source_branch = _env(
        "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME", "CI_COMMIT_REF_NAME", default=""
    )

    client = client_from_config(cfg.gitlab)
    if not default_branch:
        default_branch = client.get_default_branch(project_id)

    # Case 1: merge-request pipeline -> review that MR, post.
    if mr_iid:
        return {
            "mode": "mr", "post": True, "project_id": project_id,
            "mr_iid": int(mr_iid), "source_branch": source_branch,
            "target_branch": default_branch,
        }

    # Case 2: branch pipeline. Is there already an open MR for this branch?
    if source_branch and source_branch != default_branch:
        mr = client.find_open_mr(project_id, source_branch, target_branch=default_branch)
        if mr:
            return {
                "mode": "mr", "post": True, "project_id": project_id,
                "mr_iid": int(mr["iid"]), "source_branch": source_branch,
                "target_branch": default_branch,
            }
        return {
            "mode": "branch", "post": False, "project_id": project_id,
            "mr_iid": None, "source_branch": source_branch,
            "target_branch": default_branch,
        }

    # On the default branch (or unknown) — nothing meaningful to review.
    return {
        "mode": "none", "post": False, "project_id": project_id,
        "source_branch": source_branch, "target_branch": default_branch,
    }


def _build_prompt(job: dict) -> str:
    if job["mode"] == "mr":
        return (
            "A GitLab merge request needs review.\n\n"
            f"project_id: {job['project_id']}\n"
            f"mr_iid: {job['mr_iid']}\n\n"
            "Review this merge request following your instructions. Use "
            "get_mr_details and get_mr_changes to gather the changes, leave inline "
            "comments for concrete findings, and post an overall summary comment. "
            "Pass the exact project_id and mr_iid to every tool."
        )
    # branch mode — print only, no MR exists
    return (
        "A feature branch needs review. There is NO open merge request for it "
        "yet, so DO NOT call any MR tools (get_mr_details, get_mr_changes, "
        "post_mr_comment, post_mr_inline_comment, approve_mr) — they will fail.\n\n"
        f"project_id: {job['project_id']}\n"
        f"source_branch: {job['source_branch']}\n"
        f"target_branch: {job['target_branch']}\n\n"
        "Call get_branch_diff with these exact values to obtain what would be "
        "merged into the default branch, then review it following your normal "
        "methodology. Produce the FULL review as your final answer (verdict, "
        "summary, findings grouped by severity with file:line references). Your "
        "review will be printed in the CI job log; you cannot post comments."
    )


def _summary_posted(context) -> bool:
    """True if a post_mr_comment tool call succeeded in this conversation."""
    from agent.core.types import Role

    for msg in context.messages:
        if msg.role == Role.TOOL:
            for tr in msg.tool_results:
                if tr.name == "post_mr_comment" and not tr.is_error:
                    return True
    return False


async def _run(cfg, job: dict) -> dict:
    """Run the review. Returns {'text', 'summary_posted'}.

    In MR mode, if the model finishes without posting the summary comment, it
    is re-prompted once. Whether it posted is reported back so the caller can
    post a fallback comment directly if needed.
    """
    from agent.core.context import ConversationContext
    from agent.core.loop import run_agent
    from agent.core.types import Message, Role
    from agent.llm.registry import get_provider
    from agent.setup import build_registry, get_flavor, get_system_prompt

    provider = get_provider(cfg.llm.provider, cfg)
    flavor = get_flavor(cfg)
    registry = build_registry(cfg, flavor)
    context = ConversationContext(system_prompt=get_system_prompt(cfg, flavor))
    context.add(Message(role=Role.USER, content=_build_prompt(job)))
    result = await run_agent(provider, registry, context, max_iterations=cfg.max_iterations)
    text = result.content or ""

    summary_posted = _summary_posted(context)

    # MR mode: if it should post but didn't, re-prompt once.
    if job["mode"] == "mr" and job["post"] and cfg.gitlab.post_comments and not summary_posted:
        log.warning("MR review finished without posting a summary — re-prompting once.")
        context.add(Message(
            role=Role.USER,
            content=(
                "You have NOT yet posted your review summary to the merge request. "
                "Call post_mr_comment now with project_id="
                f"{job['project_id']} and mr_iid={job['mr_iid']}, passing your full "
                "review (verdict, summary, findings) as the body. Do this before finishing."
            ),
        ))
        result = await run_agent(provider, registry, context, max_iterations=5)
        text = result.content or text
        summary_posted = _summary_posted(context)

    return {"text": text, "summary_posted": summary_posted}


def main() -> int:
    from agent.config import apply_provider_defaults, load_config

    verbose = _is_verbose()
    _setup_logging(verbose)

    cfg = load_config()
    # CI defaults: use Qwen on Siemens AI unless overridden by env/config.
    if not os.environ.get("AGENT_LLM_PROVIDER"):
        cfg.llm.provider = cfg.llm.provider or "siemens-ai"
    if not os.environ.get("AGENT_LLM_MODEL") and not cfg.llm.model:
        cfg.llm.model = "qwen-3.8-27b"
    apply_provider_defaults(cfg.llm)

    # GitLab connection from CI env if not already configured.
    if not cfg.gitlab.base_url:
        cfg.gitlab.base_url = _gitlab_base_url()
    if not cfg.gitlab.token:
        cfg.gitlab.token = _env("GITLAB_TOKEN")

    try:
        job = _decide_target(cfg)
    except Exception as exc:
        # Errors are always surfaced.
        log.error("Could not determine what to review: %s", exc)
        return 1

    if verbose:
        log.info("CI review mode=%s post=%s project=%s branch=%s->%s mr_iid=%s",
                 job["mode"], job.get("post"), job["project_id"],
                 job.get("source_branch"), job.get("target_branch"), job.get("mr_iid"))

    if job["mode"] == "none":
        _say("On the default branch — nothing to review. Skipping.")
        return 0

    # Enforce print-only in branch mode regardless of config.
    if not job["post"]:
        cfg.gitlab.post_comments = False
        cfg.gitlab.approve = False

    if job["mode"] == "mr":
        _say(f"Reviewing merge request !{job['mr_iid']} — reading the changes and writing feedback…")
    else:
        _say(f"Reviewing branch '{job['source_branch']}' against '{job['target_branch']}' "
             "(no open merge request yet) — the review will be shown below.")

    try:
        output = asyncio.run(_run(cfg, job))
    except Exception as exc:
        log.error("The review could not be completed: %s", exc)
        return 1

    text = output["text"]

    if job["mode"] == "branch":
        print("\n" + "=" * 72)
        print(f"CODE REVIEW (no open MR for '{job['source_branch']}' -> "
              f"'{job['target_branch']}') — printed only")
        print("=" * 72 + "\n")
        print(text or "(no review produced)")
        return 0

    # MR mode: guarantee the review lands even if the model skipped posting.
    posted_via_fallback = False
    if job["post"] and cfg.gitlab.post_comments and not output["summary_posted"]:
        if text.strip():
            log.warning("Model finished without posting; posting the review directly as a fallback.")
            try:
                from agent.gitlab_client import client_from_config
                client = client_from_config(cfg.gitlab)
                body = (
                    "## Automated code review\n\n"
                    "_(posted by the review agent as a fallback)_\n\n" + text
                )
                note = client.create_mr_note(job["project_id"], job["mr_iid"], body)
                posted_via_fallback = True
                if verbose:
                    log.info("Fallback review comment posted (note id=%s).", note.get("id"))
            except Exception as exc:
                log.error("Could not post the review to the merge request: %s", exc)
                return 1
        else:
            log.error("No review was produced, so nothing was posted to the merge request.")
            return 1

    # Friendly confirmation (errors above already handled).
    if output["summary_posted"] or posted_via_fallback:
        _say(f"Done — the review has been posted to merge request !{job['mr_iid']}.")
    else:
        # post_comments disabled: the review wasn't posted by design.
        _say("Done — commenting is disabled, so the review was not posted. See it below.")
        print("\n" + text)

    # Full review text is echoed to the log only in verbose mode.
    if verbose:
        print("\n===== Review for MR !%s =====\n" % job["mr_iid"])
        print(text or "(done)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
