# Agent checkpoint 08k handoff: safe project and chat bootstrap

Date: 2026-08-27
State: implementation and synthetic validation complete; native owner acceptance remains pending

## Outcome

Agent-08k adds the missing high-level bootstrap for an external Codex, Claude
Code, or other local controller. The controller no longer has to improvise a
project POST, extract an untyped identifier, manually construct an Agent
settings body, and then submit a separate session POST before it can use
`turn`.

`prompt-enhancer agent-controller open
--acknowledge-sensitive-context-egress` reads one strict stdin envelope and:

- accepts exactly one existing project id or one new project name;
- validates the full Agent settings object before any loopback mutation;
- creates or resolves the exact project and injects its id into the live chat;
- validates both returned project and session contracts;
- never retries an ambiguous project or session creation request;
- returns `session_creation_uncertain` with the known project so the caller can
  list and reconcile chats without duplication;
- rolls back a newly created empty project only after a trustworthy 4xx session
  rejection; and
- returns `project_cleanup_unconfirmed` when that rollback cannot be proven.

The bridge contract is now `prompt-enhancer-agent-controller-cli.v3`. The Agent
Controller card exposes the new command beside discovery and native-review
continuation. It still does not start Prompt Enhancer, load a model, approve an
action, apply a write, or own a Codex/Claude process.

## Verification receipts

- Focused controller-client and stdio-CLI gate: **36 passed**.
- Agent session, command, controller, orchestration, release, and OpenAPI
  regression group: **118 passed**.
- Focused Agent/controller frontend gate: **277 passed across 4 files**.
- Complete populated-workflow Chromium gate: **66 passed** at 360 px and
  1,440 px.
- Generated OpenAPI/TypeScript parity: passed.
- Production TypeScript/Vite build: **533 modules transformed**.
- Python source and test compilation: passed.
- `git diff --check`: passed; Windows line-ending notices only.
- Ports 8765 and 8766 had no listeners after validation.

All fixtures are fictional and local. This checkpoint did not launch Prompt
Enhancer, a visible terminal, a local model, or a GPU workload.

The repository privacy scan still reports only the previously known untracked
binary screenshot `docs/checkpoint-agent-02-shell.png`; Agent-08k introduced no
new privacy finding.

## Remaining owner gate

The guarded Windows/model acceptance remains separate: real streaming, Stop,
native protected-write review, controller continuation, artifact review, model
unload, process exit, and CPU/GPU cleanup.
