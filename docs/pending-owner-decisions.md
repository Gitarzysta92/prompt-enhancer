# Pending owner decisions (2026-08-19)

This is an authorization decision log, not a statement that every existing
feature is finished. The tracks below move data across boundaries that only
the owner can authorize: another machine, another person, or a retained content
copy. Implementation defects and acceptance evidence are tracked separately in
the [application completion sweep](app-completion-sweep-2026-08-26.md).

## 1. Identity for sharing (Track 1)

Options: (a) no identity - sharing stays file-based and manual; (b) a hosted
identity provider; (c) passkeys bound to the P3a control plane
(ADR 0005 / 0008), devices enrolled per person, no passwords.

Recommendation: **(c)** when sharing is wanted at all. It keeps the app free of
passwords and third-party identity, it reuses the content-free control-plane
contracts that already exist, and every later track can name a person and a
device. Nothing is needed until a sharing track starts; (a) is the status quo.

## 2. Aggregate-only teams (Track 4)

What it is: a person publishes period aggregates (counts, metric states,
coverage - never sessions, names, or text) to a team space on the P3a control
plane; managers see distributions, never individuals (the repository rule
against rankings and single scores stands).

Decision needed: whether any aggregate may leave the machine, and the minimum
group size below which nothing is published (recommendation: five people).
Gated on 1(c).

## 3. Shared context for models (Track 2)

What it is: a user-selected shared folder (or the team space) where
*redacted, previewed, per-run approved* excerpts can be placed so a shared or
remote model can reason over them (ADR 0004's egress rules apply).

Decision needed: the threat model - who may read the folder, whether excerpts
may include code, retention. Gated on 1, 2 and the MCP surface (ADR 0014,
landed). Recommendation: defer until 1 and 2 are decided; the local models
already cover single-machine needs.

## 4. Tier 3 encrypted local content vault (#15)

Why it matters now: Claude Code keeps transcripts for a limited time
(`cleanupPeriodDays`), so text-based analysis of older sessions eventually
fails with `window_unavailable`; a vault would keep an encrypted *redacted*
window per session on this machine only.

Recommendation: opt-in, default off; key protected by the OS user credential
(DPAPI on Windows, Keychain on macOS, a passphrase elsewhere); only the
redacted analysis window is stored, never raw transcripts; a delete-all
switch; the inventory lists it as a secret-bearing path. Decision needed:
whether to hold any content copy at all, and who reviews the design before it
ships (the owner asked for a security review).

## 5. Remote annotation providers (ADR 0017, Stage 1)

Scoped and ready to build: your own model access (Opus/Fable/GPT-class,
anything OpenAI-compatible) annotates sessions after a per-provider allowance
with a destination preview; only redacted windows travel; judgments land in
the same local dataset beside your ratings. Decision needed to start: which
provider(s) and the confirmation that redacted windows may go to them under
their terms.

## What does not wait

Ratings on the Calibration page are an input only the owner can give.
An agreement pair exists only when both the human rating and a stored model
judgment are present for the same reviewed case. Judge completion must be
verified from its receipts; it must not be assumed for every indexed session.
