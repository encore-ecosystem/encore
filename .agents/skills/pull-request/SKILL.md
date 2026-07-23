---
name: pull-request
description: Prepare, create, update, validate, and monitor GitHub pull requests for the Encore repository. Use when asked to open or finish a PR, publish a branch for review, investigate failing PR checks, update a PR description, or determine whether a PR is ready to merge.
---

# Pull request workflow

Follow these steps in order. Treat a PR as finished only when its current head
commit is published, documented, fully verified, and ready for review or merge.

1. Read the repository `AGENTS.md` files that apply to the changed files.
2. Inspect the current repository state:
   - run `git status --short --branch`;
   - identify the current branch, its upstream, and the intended base branch;
   - preserve unrelated and user-owned changes;
   - do not create a PR directly from `trunk`.
3. Inspect the complete branch diff against the up-to-date base:
   - fetch the relevant remote refs;
   - review the commit list and `git diff <base>...HEAD`;
   - check for accidental files, generated artifacts, debug code, secrets,
     unrelated edits, and missing tests or documentation;
   - resolve correctness issues in the implementation instead of adding
     platform-specific workarounds that hide compiler or runtime bugs.
4. Derive a verification checklist from the actual change. Include every
   affected package, public contract, target platform, bootstrap invariant, and
   user-visible behavior. Do not infer broad correctness from a narrow test.
5. Run focused tests first, then the complete applicable local verification:
   - run tests and integration suites required by the changed components;
   - for compiler changes, verify two-stage or three-stage self-hosting and
     require the last two `extreme` compiler binaries to be identical;
   - run the CI-equivalent Docker suite before pushing when the repository
     provides one;
   - cross-check non-Linux targets locally where the available SDK, emulator,
     or Wine environment is faithful;
   - leave native OS API behavior to the corresponding native CI runner only
     when it cannot be reproduced faithfully in Docker;
   - run `git diff --check`.
6. If verification fails, inspect all failures before editing. Prepare one
   complete fixing plan, fix root causes, and rerun the applicable local suite.
   Do not use remote CI as an exploratory debugger.
7. Audit commits before publication:
   - keep commits coherent and messages descriptive;
   - commit all requested in-scope files;
   - do not rewrite published history, force-push, squash, or discard changes
     unless the user explicitly requests it;
   - confirm the worktree is clean or account for every remaining file.
8. Push the verified branch and create or update the PR against `trunk`.
   Reuse an existing PR for the branch instead of creating a duplicate.
9. Write a self-contained PR description containing:
   - a concise summary of the behavior and architecture changed;
   - important compatibility, security, migration, or platform implications;
   - the exact local verification performed;
   - explicit limitations or checks that remain CI-only;
   - related issue links when available.
   Do not claim a test or platform was verified unless there is direct evidence.
10. Confirm that the PR head SHA equals the intended local and remote branch
    SHA. A successful run for an older commit does not validate the current PR.
11. Monitor every required CI job through completion, including every native
    architecture and operating system in the matrix.
12. When CI fails:
    - collect logs from all failed jobs before making changes;
    - determine whether failures share a root cause;
    - reproduce them locally when possible;
    - implement the complete fix and rerun the applicable local/Docker suite;
    - push once per well-supported fix rather than repeatedly probing CI.
13. Perform the final readiness audit:
    - current PR head matches local and remote;
    - every required check for that SHA is `completed/success`;
    - GitHub reports the PR as mergeable with no unresolved conflicts or
      required review/status blockers;
    - the PR description still matches the implementation;
    - the worktree is clean and `git diff --check` passes.
14. If the aggregate workflow remains `in_progress` after all of its jobs are
    complete, inspect the commit check rollup, job list, deployments, and merge
    state. Treat it as a GitHub finalization issue only when all required checks
    for the current SHA are independently `completed/success` and the PR is
    `MERGEABLE/CLEAN`; otherwise continue investigating.
15. Report the PR URL, head commit, verification results, CI matrix result, and
    any remaining review requirement. Do not merge, enable auto-merge, close,
    or delete the branch unless the user explicitly asks for that action.
