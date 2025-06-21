## Memories

- When you learn something new about the project, add to CLAUDE.md

## Project Workflow & Best Practices

### Git Workflow

- **Use `git cherry-pick` to move commits between branches, not manual copying**
- Fix up commits on dev branch first, then cherry-pick clean commits to feature branches
- "cp" in git context means cherry-pick, not copy
- Cherry-pick preserves commit history and ensures all related changes are captured

### Branch Strategy

- `private/mcp-mesh-dev` - Main development branch (user can't fork their own repo)
- Create feature branches from main for PRs
- Cherry-pick comprehensive changes from dev branch to feature branches for PRs

### Issue-PR Process Flow

1. **Create GitHub issues** with proper tags for work items
2. **Checkout dev branch and reset to main** to start fresh
3. **Work on the issue** in the dev branch (all development happens here)
4. **When ready for PR:** Create feature branch from main
5. **Cherry-pick changes** from dev branch to feature branch
6. **Create PR** from feature branch → main
7. **Fix any CI issues** by continuing work on dev branch, then cherry-pick fixes to feature branch

**Why this workflow:** User can't fork their own repo, so dev branch serves as a staging area for all development before creating clean PRs.

### Architecture Notes

- System uses **heartbeat-only architecture** (not registration + heartbeat)
- Tests expect POST calls to `/heartbeat` endpoint, not `/agents/register`
- Unit tests require `asyncio.sleep(1.0)` delays for CI reliability (GitHub runners are slow)
- All 128 unit tests should pass with current architecture

### CI/CD

- Python 3.11+ required (package uses modern versions)
- Uses `pip install -e .[dev]` not requirements-dev.txt
- Focus on unit tests only (integration/e2e tests removed due to complexity)
- Generated files excluded from linting via ruff configuration
- **Code quality issues:** 48 linting errors in source code need fixing
- Test files have relaxed quality requirements (tests/\*\* excluded from strict checks)
