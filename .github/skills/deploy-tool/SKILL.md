---
name: deploy-tool
description: "Deploy the current Delft3D File Manager changes to GitHub when the user says 'deploy tool'. Read the release version from Delft3DFileManager/metadata.txt, commit changes, push the current branch, create the matching v<version> Git tag, and push that tag to origin."
argument-hint: "Optional release note or commit message"
---

# Deploy Tool

## When to Use

Use this skill when the user says `deploy tool` or explicitly asks to perform the repository deployment workflow.

## Procedure

Run the following from the repository root in PowerShell:

1. Inspect the repository state with `git status --short --branch`.
2. Read the first non-empty `version=` entry from `Delft3DFileManager/metadata.txt`.
3. Validate that the version matches `^[0-9]+\\.[0-9]+\\.[0-9]+$`. Set the tag to `v<version>`.
4. Confirm the current branch is not detached and that `origin` exists.
5. Check whether the release tag already exists locally or on `origin`. Stop and report the conflict rather than moving or replacing an existing tag.
6. Stage all intended repository changes with `git add -A`. Review the staged summary with `git diff --cached --stat`.
7. Commit the staged changes. Use the supplied release note as the commit message when provided; otherwise use `Release v<version>`.
8. Push the current branch to GitHub with `git push origin HEAD`.
9. Create an annotated tag with `git tag -a v<version> -m "Release v<version>"`.
10. Push the exact version tag with `git push origin v<version>`.
11. Report the commit, branch push, and tag push results.

## Safety Rules

- Ask for confirmation immediately before the first remote-changing command if the user did not explicitly request deployment in the current message. The exact phrase `deploy tool` is explicit authorization for this workflow.
- Never use `git reset --hard`, force-push, delete tags, or overwrite an existing tag.
- Do not proceed if the version is missing, ambiguous, malformed, or differs from an existing matching tag.
- Do not commit unrelated changes silently. Show the staged summary and ask the user to remove anything unintended before committing when the working tree contains unexpected files.
- If there are no changes to commit, do not create a release commit solely for the tag. Report that the tree is clean and ask whether an existing commit should be tagged.
- If any command fails, stop immediately and report the failed command and its output; do not continue to tagging or pushing.
