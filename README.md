# mr-review-agent

An automated **GitLab Merge Request reviewer** built on the Lambda-first agent
framework. A GitLab webhook fires on every MR open/update; API Gateway invokes
this Lambda; the agent fetches the diff via the GitLab API, reviews it with an
LLM, and posts inline comments + a summary back on the MR.

```
GitLab (Merge request events webhook)
      │  POST
      ▼
API Gateway ──► Lambda (agent.lambda_handler.lambda_handler)
                      │  runs the "mr_review" agent (ReAct loop)
                      ▼
                GitLab REST API  ◄── fetch diffs / post review
```

## What it reviews

Correctness, security (injection, secrets, authz), reliability (leaks, missing
timeouts, swallowed errors), maintainability, test coverage, and consistency.
Findings are classified **blocker / major / minor / nit**, posted as inline
comments (with GitLab `suggestion` blocks where useful) plus one summary
comment with a verdict.

## Project layout

```
mr-review-agent/
├── config.yaml                 # LLM + GitLab settings (secrets via env)
├── sample_webhook_event.json   # example GitLab MR webhook payload
├── pyproject.toml / requirements.txt
└── src/agent/
    ├── core/ tools/ llm/ flavors/   # the framework (unchanged)
    ├── config.py               # + GitLabConfig section
    ├── gitlab_client.py         # minimal GitLab REST v4 client
    ├── lambda_handler.py        # parses GitLab MR webhook -> review prompt
    └── agents/mr_review/
        ├── instructions.md      # the reviewer's system prompt
        └── tools/
            ├── _base.py                    # GitLabTool base (config + client)
            ├── get_mr_details.py
            ├── get_mr_changes.py
            ├── get_file_content.py
            ├── post_mr_comment.py
            ├── post_mr_inline_comment.py
            └── approve_mr.py
```

## Tools the agent has

| Tool | Purpose |
|------|---------|
| `get_mr_details` | MR title/description/author/branches/commits |
| `get_mr_changes` | per-file unified diffs (primary review input) |
| `get_branch_diff` | branch-vs-default diff for the no-MR CI case |
| `get_file_content` | full file at a ref for extra context |
| `post_mr_inline_comment` | line-anchored comment (auto-resolves diff SHAs) |
| `post_mr_comment` | overall review summary comment |
| `approve_mr` | approve (disabled unless `gitlab.approve=true`) |
| `bash` | built-in shell tool (inherited from the framework) |

## Configuration

`config.yaml` is overlaid by environment variables (which win). In Lambda, set
secrets as env vars — do not commit them.

| Env var | Purpose |
|---------|---------|
| `GITLAB_URL` | e.g. `https://gitlab.example.com` (no `/api/v4`) |
| `GITLAB_TOKEN` | PAT/Project token with **`api`** scope |
| `GITLAB_POST_COMMENTS` | `true`/`false` — allow posting (default true) |
| `GITLAB_APPROVE` | `true`/`false` — allow auto-approve (default false) |
| `AGENT_API_KEY` / `AGENT_SIEMENS_API_KEY` | LLM gateway key |
| `AGENT_LLM_PROVIDER` / `AGENT_LLM_MODEL` | override provider/model |

## Run in GitLab CI (recommended today)

Because the GitLab instance is internal-only (not reachable from the public
internet), the simplest way to run the agent **now** is inside a GitLab CI job:
the runner already reaches GitLab, and it can reach the public Siemens AI
gateway outbound. No VPC required. (The Lambda entry point is kept for a later
VPC-based webhook deployment — see below.)

The CI entry point is `ci_entry.py`. It auto-detects the situation from GitLab's
predefined CI variables:

| Situation | What it does |
|-----------|--------------|
| Merge-request pipeline (`CI_PIPELINE_SOURCE == merge_request_event`) | Reviews `CI_MERGE_REQUEST_IID` and **posts** comments to that MR |
| Feature branch, an open MR (branch → default) already exists | Reviews that MR and **posts** comments to it |
| Feature branch, **no** MR yet | Compares the branch against the **default branch** (`get_branch_diff`) and **prints** the review in the job log |
| On the default branch | Skips (nothing to review) |

This repo both **hosts** the agent and **self-tests** it. The `.gitlab-ci.yml`
here defines a `code_review` job (stage `review`) that runs the agent against
this repo's own MRs/branches — a working example of what other projects will
do. It uses the hardened Python image:

```
${HARBOR_REGISTRY}/container-hardening-service/python:3.11.16-dtx26.09.01-trixie
```

Because the agent code lives in this repo, the self-test job installs
`requirements.txt` and runs `ci_entry.py` directly (no clone).

Setup for THIS repo (self-test): add masked CI/CD variables
(Settings → CI/CD → Variables):
   - `AGENT_SIEMENS_API_KEY` — Siemens AI gateway key (`SIAK-...`)
   - `GITLAB_TOKEN` — a token with the **`api`** scope (project/group access
     token or PAT). `CI_JOB_TOKEN` alone cannot post notes.
   - Optional: `AGENT_LLM_MODEL`, `GITLAB_VERIFY_SSL` / `GITLAB_CA_BUNDLE`,
     `AGENT_VERBOSE`.

Setup for OTHER repos (consumers): use the commented `code_review_external`
template at the bottom of this repo's `.gitlab-ci.yml`. It clones the agent from
`…/pd-analyzer/review-agent`, installs it, and runs `ci_entry.py` against the
consuming repo. Set the same masked variables there.

Both variants are `allow_failure: true` so a review never blocks the pipeline.

### Output verbosity

By default the CI job prints **friendly, non-technical progress** (e.g.
"Reviewing merge request !503 — reading the changes and writing feedback…",
"Done — the review has been posted to merge request !503."). Errors are always
shown. To see the **full technical logs** (every tool call, HTTP request, and
loop iteration — the original behavior), set `AGENT_VERBOSE=true` (or
`AGENT_DEBUG=true`, or pass `--verbose`/`-v`).

The post-completion fallback (re-prompt once, then post the review directly if
the model skipped it) applies **only in MR mode**. Branch mode is always
print-only.

Feature-branch diffs are always evaluated **in the context of the default
branch** (via the compare API using the merge-base), matching what an MR would
show.

## Deploy to Lambda (later — needs VPC)

1. Package `src/` + deps into a Lambda zip (or container). Handler:
   `agent.lambda_handler.lambda_handler`. Runtime: Python 3.10+.
   Recommended timeout: 300–900s; memory: 512MB+.
2. Set env vars: `GITLAB_URL`, `GITLAB_TOKEN`, `AGENT_API_KEY` (and provider
   overrides as needed).
3. Put the Lambda behind API Gateway (HTTP API, POST route).
4. In GitLab: **Project → Settings → Webhooks**, add the API Gateway URL,
   enable **Merge request events**, set a **Secret token**, and save.
   (Optionally verify `X-Gitlab-Token` in the handler for defense in depth.)

The handler returns HTTP 200 even for ignored/errored events so GitLab does not
auto-disable the webhook. It reviews `open` / `reopen`, and `update` only when
new commits changed the diff; drafts/WIP are skipped.

## Local test (offline)

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e .
# Dry parse of the sample webhook (no network/LLM):
python - <<'PY'
import json
from agent.lambda_handler import _parse_gitlab_mr, _should_review, _build_review_prompt
ev = json.load(open("sample_webhook_event.json"))
p = _parse_gitlab_mr(ev); print(p); print("review?", _should_review(p))
print(_build_review_prompt(p))
PY
```

To exercise it end-to-end, set `GITLAB_URL`/`GITLAB_TOKEN`/`AGENT_API_KEY` and
invoke `lambda_handler` with the sample event as the `body`.

## Adding checks or new agents

- Tweak the review behavior by editing `agents/mr_review/instructions.md`.
- Add a capability by dropping a new `Tool` subclass into
  `agents/mr_review/tools/` — it is auto-discovered, no wiring needed.
- Add a whole new agent by creating another folder under `agents/` and setting
  `AGENT_FLAVOR`.
