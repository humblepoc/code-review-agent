# AI Review Agent — Integration Guide

Add automated AI code review to your GitLab project. On every merge request the
agent reads the diff, reviews it, and posts inline comments plus a summary with
a verdict. Findings are labelled by severity: 🔴 blocker, 🟠 major, 🟡 minor,
⚪ nit. All comments are prefixed with **"AI Review Agent:"**.

You do **not** need to add any agent code to your repo — just an `include` and
two CI/CD variables.

## 1. Add the include to your `.gitlab-ci.yml`

```yaml
include:
  - project: 'xfm/components/enablement/tools/pd-analyzer/review-agent'
    ref: main
    file: '/ci/review-agent.gitlab-ci.yml'

stages:
  - review        # add this stage, or merge 'review' into your existing stages
```

## 2. Add two CI/CD variables

In your project: **Settings → CI/CD → Variables**. Add both as **Masked** and
**not Protected** (unless your review branches are protected):

| Variable | Value |
|----------|-------|
| `GITLAB_TOKEN` | A token with the **`api`** scope (a Project Access Token is recommended). Used to read the diff and post comments. `CI_JOB_TOKEN` is not sufficient. |
| `AGENT_SIEMENS_API_KEY` | Your Siemens AI gateway key (`SIAK-...`). |

That's it. The next pipeline will run a `code_review` job.

## What to expect

| When the pipeline runs on… | What the agent does |
|----------------------------|---------------------|
| A merge request | Reviews the MR and **posts** inline comments + a summary to it |
| A feature branch that already has an open MR | Reviews that MR and **posts** to it |
| A feature branch with no MR yet | Reviews the branch against your default branch and **prints** the review in the job log (nothing is posted) |
| Your default branch | Nothing to review — skipped |

The `code_review` job is `allow_failure: true`, so a review never blocks your
pipeline.

## Optional settings

Set these as CI/CD variables only if you want to change the defaults:

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_LLM_MODEL` | `qwen-3.8-27b` | Override the model |
| `GITLAB_APPROVE` | `false` | If `true`, the agent may approve MRs with no blocking findings |
| `GITLAB_CA_BUNDLE` | — | Path to an internal CA bundle (alternative to skipping TLS verification) |
| `AGENT_VERBOSE` | `false` | If `true`, print full technical logs instead of friendly progress |

## Notes

- Pin `ref:` to a release tag or commit SHA instead of `main` if you want a
  stable, reproducible review configuration.
- Drafts / WIP merge requests are skipped.
- Feature-branch diffs are always evaluated in the context of your default
  branch (what the eventual MR would show).
