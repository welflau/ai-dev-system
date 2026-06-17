Create a pull request for the current branch.

Gather context first:
1. Run `git log main..HEAD --oneline` to see commits
2. Run `git diff main...HEAD --stat` to see changed files

Then create the PR:
```bash
gh pr create --title "<title>" --body "<summary of changes>"
```

Use conventional commit style for the title. Keep the body concise — what changed and why.
