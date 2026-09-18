# AI Review Agent — Integration Guide

Add the following to your project's `.gitlab-ci.yml`:

```yaml
include:
  - project: 'xfm/components/enablement/tools/pd-analyzer/review-agent'
    ref: main
    file: '/ci/review-agent.gitlab-ci.yml'

stages:
  - review        # add this stage, or merge 'review' into your existing stages
```

Then add two **Masked** CI/CD variables (Settings → CI/CD → Variables):

| Variable | Value |
|----------|-------|
| `GITLAB_TOKEN` | A token with the **`api`** scope (Project Access Token recommended). |
| `AGENT_SIEMENS_API_KEY` | Your Siemens AI gateway key (`SIAK-...`). |
