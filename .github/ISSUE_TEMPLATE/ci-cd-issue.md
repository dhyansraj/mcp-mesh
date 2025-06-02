---
name: CI/CD Issue
about: Report issues with continuous integration or deployment
title: "[CI/CD] "
labels: ["ci/cd", "bug"]
assignees: ""
---

## CI/CD Issue Description

**Which CI/CD component is affected?**

- [ ] GitHub Actions workflow
- [ ] Test execution
- [ ] Code quality checks
- [ ] Security scanning
- [ ] Build/packaging
- [ ] Release automation
- [ ] Dependency updates

**Workflow/Job Details**

- Workflow name:
- Job name:
- Run ID/URL:

## Problem Description

**What happened?**
A clear description of what went wrong.

**Expected behavior**
What should have happened instead.

**Error messages/logs**

```
Paste any relevant error messages or logs here
```

## Environment Information

**GitHub Actions Environment:**

- Runner OS: [e.g., ubuntu-latest, windows-latest]
- Python version: [e.g., 3.11]
- Branch: [e.g., main, feature/xyz]

**Local Environment (if applicable):**

- OS: [e.g., macOS, Ubuntu 20.04, Windows 10]
- Python version: [e.g., 3.11.5]
- Virtual environment: [Yes/No]

## Reproduction Steps

If this is reproducible locally:

1. Step 1
2. Step 2
3. Step 3
4. See error

**Local CI test command:**

```bash
python scripts/run_ci_tests.py
```

## Additional Context

**Recent changes:**

- [ ] Dependencies updated
- [ ] Code changes
- [ ] Configuration changes
- [ ] New tests added

**Frequency:**

- [ ] Always fails
- [ ] Intermittent failure
- [ ] First occurrence

**Impact:**

- [ ] Blocks all PRs
- [ ] Blocks releases
- [ ] Reduces confidence in tests
- [ ] Performance impact

## Possible Solution

If you have ideas for fixing this issue, please describe them here.

## Checklist

- [ ] I have checked recent workflow runs for similar issues
- [ ] I have tried reproducing this locally
- [ ] I have checked the documentation
- [ ] I have included all relevant error messages
