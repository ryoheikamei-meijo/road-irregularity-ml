---
name: github-open-pr
description: Open a GitHub pull request for this repository from local changes. Use when Codex needs to review the working tree, align branch names and commit messages with README.md conventions, push the branch, and create a draft PR with an accurate title and body.
---

# GitHub Open PR

## Overview

Open a draft PR that matches this repository's workflow and avoids leaking generated experiment data.
Read `README.md` before deciding branch names, commit messages, or what files are safe to include.

## Workflow

### 1. Inspect the change set

Run these checks first:

```bash
git status --short
git diff --stat
git diff --cached --stat
```

Then:

- Read `README.md` and extract the branch naming and commit message rules for the current task.
- Inspect unstaged and staged diffs before preparing a PR.
- Treat `data/raw/`, `data/features/`, and `data/processed/` as non-committable by default. Include them only if the user explicitly asks.
- Stop and ask the user if unrelated changes are mixed into the same working tree and the intended PR scope is ambiguous.

### 2. Align the branch name

- Use the prefix rules from `README.md`:
  - `feat/xxxxx`
  - `fix/xxxxx`
  - `refactor/xxxxx`
  - `docs/xxxxx`
  - `chore/xxxxx`
  - `test/xxxxx`
- Write the suffix in lowercase kebab-case.
- If the current branch violates the convention and has not been shared yet, rename it with `git branch -m <new-name>`.
- If the branch is already pushed or renaming would disrupt collaboration, explain the mismatch instead of renaming silently.

### 3. Prepare the commit

- Prefer a single coherent PR. Split commits only when the change set contains clearly separable concerns.
- Review the actual staged diff before committing:

```bash
git diff --cached
```

- Follow the repository commit format exactly:

```text
type(scope): summary
```

- Use `type` from `feat`, `fix`, `refactor`, `docs`, `chore`, `test`.
- Keep `scope` short and concrete.
- Write `summary` in Japanese.
- Avoid generic subjects such as `update files` or `fix bug`.
- If a repository-local commit helper skill exists and the user explicitly invokes it, defer to that skill. Otherwise commit directly with non-interactive git commands.

### 4. Push the branch

- Confirm the target remote before pushing:

```bash
git remote -v
```

- Push with upstream tracking when needed:

```bash
git push -u origin HEAD
```

Use plain `git push` only when upstream is already configured.

If push fails because of authentication, non-fast-forward, or protected-branch rules, report the exact blocker and avoid inventing a workaround.

### 5. Create the draft PR

- Prefer the GitHub plugin or connector when available.
- Otherwise use `gh pr create --draft` with explicit title and body.
- Infer the base branch from `origin/HEAD` when possible. If it is still ambiguous, ask the user instead of guessing.
- Derive the PR title from the branch purpose and latest commit, not by copying the branch name verbatim.
- Write a concise PR body that includes:
  - background or problem
  - main changes
  - validation performed
  - data/privacy note when relevant

## Output Rules

- Report the branch name, commit hash, push result, and PR URL after creation.
- If any step was skipped, state exactly why.
- Keep all git operations non-interactive.
- Do not force-push unless the user explicitly asks.
