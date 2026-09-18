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
