# CLAUDE.md

Public **code** repository (`zenkio/hk-history-research`): `scripts/`, `tests/`, `quartz/`, site config, workflows.
Content, research, state, `BACKLOG.md` and `PRODUCT.md` live in the private `zenkio/hk-history-data`.
**Never copy content, research notes, state files or pipeline output here** (code, issues, PRs, workflow logs).

## Start here
- Read `BACKLOG.md` (data repo) first, then `PRODUCT.md`. New ideas go to the backlog Inbox; do not start them unprompted.
- Follow [`docs/AUTONOMOUS_WORKING_AGREEMENT.md`](docs/AUTONOMOUS_WORKING_AGREEMENT.md) (continue autonomously, ask only real blockers, owner-only tasks go in `docs/MANUAL_TASKS.md`).
- Pipeline, model pool, evidence, seeding, photos, videos, repair, workflows: [`docs/PIPELINE.md`](docs/PIPELINE.md) (read the part you need, not all of it).
- Agent HQ: `bash scripts/hq.sh doctor` first; never print `$HQ_TOKEN`. Standing order and owner rules are in project memory.

## How it fits together
Workflows check out hk-history-data as the working folder (secret `DATA_REPO_TOKEN`) and copy this repo's code over it, so scripts read/write `content/` and `scripts/state/` there and push to its `main`. `quartz/` must stay committed. Deploy publishes the built site only.

## Build and test
```bash
npm ci && npm run install-plugins && npm run quartz -- build      # site
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q                                          # offline; run inside the data clone with code copied over for real-content checks
```
- Every bug fix comes with a test that fails on the old code (name the PR in a comment). Tests must pass before a PR is opened or updated.
- Re-run only failing tests while fixing; do not re-run unchanged green suites.

## Rules
- Production changes (live site, DNS, paid services, deleting data) need the owner's authorisation. Never weaken validation or publication gates; green CI is not historical verification.
- **One open project PR at a time across both repos**; add follow-ups to it. New branch after every merge: `git fetch origin && git checkout -b vibe-coding-$(date -u +%Y%m%d-%H%M) origin/main`. Never reuse a merged branch.
- Merge autonomously only when required checks are green and policy permits; never bypass protection. Fetch the data repo right before branching/pushing (pipeline commits hourly).
- Replies: Done / CI / Next / Blocked, under 60 words; details go in repo notes.
