---
doc_id: how-i-can-revert-a-commit-in-git
title: How I can revert a commit in git
doc_type: guide
tags: [commit, git, revert]
source: approved-draft-38b89c2033
source_question: How I can revert a commit in git?
approved_by: admin:admi…
approved_at: 2026-10-28T22:56:19+00:00
---

# How I can revert a commit in git

### How to Revert a Commit in Git

You can revert a commit using the `git revert` command, which creates a new commit that undoes the changes introduced by the specified commit.

```bash
git revert <commit-hash>
```

- Replace `<commit-hash>` with the ID of the commit you want to revert.
- This is a safe option for undoing changes because it does not rewrite history; instead, it adds a new commit.

### Example

```bash
git revert abc1234
```

This will open your editor to provide a commit message for the revert commit. Save and close the editor to complete the revert.

### Alternative: Reset (Warning)

If you want to completely remove the commit from history (for example, in local branches only), you can use:

```bash
git reset --hard <commit-hash>^
```

But be cautious: this rewrites history and can cause issues if the commit was already pushed and shared.

---

**Note:** Your team’s git workflow might have preferred ways to undo changes; check conventions if in doubt.
