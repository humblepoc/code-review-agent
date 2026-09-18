# AI Review Agent - Integration Guide

Add the following to your project's `.gitlab-ci.yml`:

```yaml
include:
  - project: 'your-group/code-review-agent'
    ref: main
    file: '/ci/review-agent.gitlab-ci.yml'

stages:
  - review        # add this stage, or merge 'review' into your existing stages
```
