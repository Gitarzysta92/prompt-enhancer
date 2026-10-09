# ADR 0019: Owner-reviewed architecture and contributions

- Status: records the owner's existing collaboration decision; this document is
  subject to owner PR review.
- Date: 2026-10-08
- Scope: all contributors, coding agents, architecture changes and release work.

## Context

Multiple people and agents can work independently, but changes to metrics,
privacy, runtime ownership and persistence can affect several surfaces. The
owner wants collaborators to propose improvements while retaining final control.

## Decision

Every contributor works on an approved task and feature branch. Changes enter
through a PR targeting `main`; the owner is the final reviewer and merge
authority. Agents and contributors do not self-merge, force-push the primary
branch, change repository visibility or publish releases automatically.

Any collaborator may propose an ADR. The proposal states context, alternatives,
trade-offs, affected component IDs, migration/compatibility implications and
required tests. A proposal does not supersede an accepted ADR until the owner
accepts it. Add a superseding record rather than silently rewriting history.

The task card names a reproducible source baseline and dependency PRs. Local
unpublished work is preserved and cannot be assumed present on main. Each PR
states the evidence level reached and the remaining acceptance requirements.

## Alternatives

Direct shared-main editing loses review boundaries and increases accidental
overwrites. Unrestricted agent merge authority removes the owner's control.
Requiring owner authorship of every proposal would prevent useful collaboration.
Feature branches with owner review support parallel contribution and reviewable
decisions without requiring those alternatives.

## Consequences and enforcement

Written policy, a metadata CI check and branch protection are different things.
This ADR does not establish GitHub enforcement or change repository permissions.
Verify available platform controls separately; never claim policy prevents a
collaborator from exercising permissions that GitHub actually grants.

Review scope/privacy, meaningful tests, source/publication state and migration
risks before merging. Owner acceptance is not a substitute for failing gates.
See `AGENTS.md`, [collaboration workflow](../collaboration-workflow.md) and
[change recipes](../architecture/change-recipes.md).
