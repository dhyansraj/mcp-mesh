---
description:
auto_execution_mode: 3
---

- dev branch = `private/mcp-mesh-dev`

* Ask user for the summary of the issue
* Create a GitHub issue using gh command
* Make sure we are in dev branch and all changes are commited
* fetch latest main
* create a fix/feature branch based on the issue from main branch
* cherry pick commits for this issue from dev branch
* Ask user to review branch and commits
* Upon user permission, push the commits and create PR using gh command
