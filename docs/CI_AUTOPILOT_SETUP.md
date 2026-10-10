# CI Autopilot setup

This repository can run Claude Code as an event-triggered engineering agent. The workflow starts on same-repository PR updates, checks GitHub CI status, attempts bounded repairs, and continues the backlog while preserving evidence and publication gates.

## One-time setup

1. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**.
2. Add `ANTHROPIC_API_KEY` using an API key from the Anthropic Console. Claude API usage is billed separately; set an appropriate spend limit in Anthropic.
3. Ensure Actions are enabled and the repository's Actions token policy allows the workflow permissions declared in `.github/workflows/claude-ci-autopilot.yml`.
4. Merge the workflow PR only after the existing required checks pass.
5. To start the agent on an already-open PR after setup, add a PR comment containing `@autopilot`. Future non-draft, same-repository PRs start automatically on open/reopen/update.

## Behaviour and safety

- The agent waits for CI checks for the current head SHA, with a 20-minute polling limit and at most two repair cycles per run.
- It never treats an unknown or pending CI status as green.
- It must not bypass branch protection or required reviews.
- Historical publication/verification status and evidence records remain protected by explicit evidence gates.
- The workflow does not run automatically on fork PRs, and it ignores commits made by `claude[bot]` as new triggers to avoid recursive runs. The active run is expected to monitor checks after its own fixes.
- A job has a 45-minute runtime and 20 Claude turns. If it hits a limit or a permission gate, the PR should contain the blocker and next action.

## Cost and security

This workflow grants write access to repository contents and PRs so the agent can update its own PR branch. Only enable it for a repository where you trust PR authors with write access. Treat CI output and repository content as untrusted; never put unrelated credentials in Actions secrets. The Anthropic API key is required; no PAT is required for the workflow as written.
