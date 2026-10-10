# Autonomous working agreement — HK History Research

This is the shared operating policy for ChatGPT, Claude Code, and any other coding agent working on this project. Follow it whenever the owner asks to continue, fix, audit, implement, or otherwise work on HK History Research, even if the request is only “continue”.

## Default mode: continue autonomously

- Treat a project-work request as permission to inspect the real repository state and execute the next appropriate work, not merely propose a plan.
- Read the private data repository's `BACKLOG.md` first, then `PRODUCT.md` and relevant implementation notes. Follow the active milestone and ordered priorities; do not invent new scope.
- Continue through related tasks without asking for approval after each step. Make reasonable, reversible implementation choices consistent with documented decisions.
- **Ask decision/clarification questions promptly while the owner is present.** If any choice, approval, credential, interpretation, or clarification is genuinely needed, ask as soon as it is identified, preferably bundle all currently known questions into one concise message, and then continue every independent task that does not depend on the answer. Do not silently defer questions until the end or let avoidable unanswered decisions block unrelated development.
- If a task depends on an answer, mark that exact dependency in `docs/MANUAL_TASKS.md`, explain the options and your recommended default, and move to other safe work. Resume the blocked task as soon as the owner answers.
- Ask only when blocked by a genuinely owner-controlled decision (e.g. a material product/scope/cost choice), missing access/credentials, an ambiguous instruction that could cause materially different outcomes, or a destructive/high-risk action not already authorised.
- Do not stop after writing a plan, opening a PR, seeing a CI run start, or reporting progress. Work through the next safe step and re-check outcomes.

## CI and execution continuity

- Before triggering CI, inspect the latest checks and determine whether an equivalent run is already in progress. Do not start a duplicate run unnecessarily.
- While CI is running, work on independent, safe tasks where possible. Then check the existing run again; do not just tell the owner to wait.
- On failure, inspect the logs/results, identify the cause, fix it, run relevant tests, update the existing work branch/PR, and repeat. Do not report a failure as the end of the task when it is actionable.
- If a tool fails or returns incomplete data, retry or use another available repository operation when reasonable; distinguish confirmed facts from assumptions.
- Persist concise progress, decisions, current branch/PR, CI status, blockers, and exact next steps in the appropriate project record so another session can resume without redoing work. Keep private research/data out of the public repository and public logs.
- Maintain `docs/MANUAL_TASKS.md` as a durable ledger of every task that truly requires the owner or an interactive browser session. Add items as soon as discovered; mark them done only after confirmation/evidence. Include why an agent cannot safely finish it, the exact user action, and a ready-to-paste prompt for Claude's browser capability if it can execute the task, or a Gemini browser prompt if Gemini can only guide the user. Never ask the owner to do work an available connected tool can already perform.
- A ChatGPT turn can still end due to execution/time/tool limits. Never claim to run indefinitely or to receive GitHub event notifications after the turn ends. Before a turn ends, leave a durable checkpoint and complete as much safe work as possible.

## Git and PR workflow

- Respect the project's one-open-PR-at-a-time rule across both repositories. If a project PR is already open, add coherent follow-up work to its existing branch and update that PR rather than creating another one. Do not mix unrelated changes merely to obey this rule; if the existing PR is unrelated, finish/resolve it first where authorised or clearly record the conflict.
- Use a fresh branch from the latest appropriate base after each merge. Fetch/check current repository state immediately before branching and pushing because the private data repository's pipeline can update `main` hourly.
- Run relevant tests before updating the PR. Keep the PR description accurate and update it as scope evolves.
- The owner has authorised autonomous progress and merging when all required CI checks are green. Merge only when the checks required by repository policy have actually passed, the PR is mergeable, and no unresolved review/branch-protection requirement blocks it. Never bypass protection, required reviews, or failing/unknown checks. If GitHub refuses the merge, report the exact blocker and continue other safe work.
- After merge, verify the merge result and resulting CI/deployment state, then continue with the next backlog item in a new branch as appropriate.

## History integrity and safety — non-negotiable

- Software CI passing proves software checks passed; it does not prove historical claims are true.
- Never mark content published, verified, or historically established merely because code/tests/pipelines are green.
- AI-generated content remains a hypothesis until claim-level evidence and the project's publication gate satisfy the documented requirements.
- Preserve source rights, provenance, contradictions, uncertainty, and fail-closed publication safeguards. Do not silently weaken tests or gates to make CI green.
- Keep migration and live-data changes preview-only unless the active backlog and explicit project decisions authorise the next step.
- Never copy private content, research notes, evidence state, or pipeline output into the public code repository, its PR descriptions, issues, or public workflow logs.

## How to report

- Be concise and factual. Report what changed, links to the relevant PR/commit, exact CI status, what was merged (if anything), and the next concrete task.
- Do not claim that a check, merge, deployment, or publication succeeded unless you verified it.
- If a hard execution limit or genuine blocker prevents completion, say what stopped, what was completed, and where the next session should resume. Do not frame avoidable early stopping as a system limitation.
