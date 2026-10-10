# Manual tasks and owner decisions

This file is the durable hand-off ledger for actions that genuinely require the project owner or an interactive browser session. Keep it current so ChatGPT, Claude Code, and future agents can resume without rediscovering blockers.

## Rules for agents

- Add a task as soon as it is discovered; do not wait until the end of a session.
- Ask the owner promptly about decisions/clarifications while they are present. Bundle currently known questions into one concise message. Do not let a pending answer block unrelated safe work.
- For each open task, state the exact dependency, why connected tools or code cannot complete it, the smallest action needed, and a recommended choice where useful.
- Check whether a connected GitHub/app tool can do the work before asking the owner to use a browser.
- If a browser-based task is genuinely possible, provide a ready-to-paste prompt for the relevant Claude browser capability. If Claude cannot execute it but Gemini browser can guide the owner, provide a Gemini prompt that guides the owner step by step. Do not claim either tool can perform an action unless its current capabilities and access support it.
- Never put secrets, API keys, private research text, personal data, or private repository content in this public repository. Record only a generic task description here; keep sensitive specifics in the private `hk-history-data` repository.
- Mark a task complete only after observing a success result or receiving the owner's confirmation. Record evidence briefly.
- If no human task is currently known, say so and leave this file as the template; do not invent tasks just to populate it.

## Open tasks

### [OPEN] Resolve Trove API access and permitted-use terms

- **Why human interaction is required:** Trove's access process may require an API key, an account-specific application, and answers about intended use. The owner must verify and approve any representations made to the archive and accept applicable terms. No key or permission should be assumed to exist.
- **Blocks:** Any Trove API integration that needs authenticated access, and any use of Trove material beyond the currently approved metadata-only workflow. Independent source-coverage and inspectable-passage work can continue.
- **Owner decision/action:** The owner has not replied to Trove because future monetisation is undecided. No application response, API key, or permission is confirmed. No action is needed until the owner decides whether the app may use donations, ads, paid extras, or remain entirely free; then review Trove's current terms and draft a truthful response for owner review. Never promise non-commercial use while the product model is undecided.
- **Agent recommendation:** Keep Trove metadata-only until the archive's requirements and any relevant permissions are clear. Do not fetch or send restricted full text/OCR to an AI service based on API availability alone.
- **Claude browser prompt:** `For my HK History Research project, inspect Trove's official API access and usage requirements using my authorised logged-in browser session. Determine whether an API key/application is needed and identify the questions and terms that require my confirmation. Draft accurate proposed answers based on the project purpose, but do not invent facts, submit the application, accept terms on my behalf, or reveal/store any key. Stop at the review step and report the official page URLs, required owner decisions, and next safe action.`
- **Gemini browser guide prompt:** `Guide me through Trove's official API access/usage process one step at a time. Tell me what page to open and what each question or term means in plain English. Help me draft truthful answers for my HK History Research project, but wait for my confirmation at each step and do not ask me to paste passwords or API keys into chat. Stop before final submission or acceptance of terms and tell me what non-sensitive confirmation to report to my coding agent.`
- **Resume when:** The owner decides the intended funding model and confirms the permitted-use response, or provides non-sensitive confirmation that access/terms are resolved. Store any secret only in the appropriate private secret store, never in repository files or this public ledger.
- **Status/evidence (2026-10-10):** Owner has not replied to Trove; monetisation remains undecided. No API key or permission has been verified. Continue independent P1 work and metadata-only discovery where permitted.

## Task template

Copy this block for each new item:

### [OPEN] Short task title

- **Why human interaction is required:** Explain the missing permission, login, visual confirmation, product decision, or external action that an agent cannot safely perform.
- **Blocks:** Name only the work that depends on this task; list independent work that can continue.
- **Owner decision/action:** State the exact question or smallest sequence of actions required.
- **Agent recommendation:** Give a default recommendation and the reason, when a recommendation is appropriate.
- **Claude browser prompt:** Provide a ready-to-paste prompt only if Claude's available browser capability can genuinely execute the task. Ask it to stop before any irreversible/destructive action unless already authorised.
- **Gemini browser guide prompt:** If Gemini can guide rather than execute, provide a ready-to-paste prompt requesting one step at a time, explain what the owner should see, and ask the owner to report the result before proceeding.
- **Resume when:** State the observable condition that unblocks the agent.
- **Status/evidence:** Keep this short; link to the relevant settings page/PR or record non-sensitive confirmation.

## Reusable browser prompts

Use these only after replacing the bracketed details and confirming the target task is appropriate for the browser tool.

### Claude browser — execute a bounded task

> Complete this specific task for my HK History Research project: [TASK]. Use only the relevant logged-in website and account I authorise. First inspect the current state and explain the exact changes you intend to make. Execute reversible, clearly scoped steps without asking me to approve each click. Stop and ask me before any irreversible action, payment, deletion, publication, permission escalation, or change whose consequences are unclear. Do not expose secrets or copy private project data into public places. Verify the final state and report what changed, what could not be done, and any evidence of success.

### Gemini browser — guide the owner step by step

> Guide me through this task for my HK History Research project: [TASK]. You may guide me through the browser, but do not claim to control or change the page unless your current tool actually does so. Give me one small step at a time, tell me what I should see, and wait for me to confirm the result before giving the next step. Explain any consequential choice in plain language and recommend a safe default. Do not ask me to reveal passwords, API keys, recovery codes, or other secrets in chat. At the end, help me verify the result and tell me what non-sensitive confirmation to report to my coding agent.
