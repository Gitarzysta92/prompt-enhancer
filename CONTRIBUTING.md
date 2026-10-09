# Contributing

Thank you for helping build Prompt Enhancer. Privacy and measurement validity are part of correctness, not optional polish.

Start with the [architecture atlas](docs/architecture/README.md),
[change recipes](docs/architecture/change-recipes.md), and
[collaboration workflow](docs/collaboration-workflow.md). Any collaborator may
propose an architecture improvement through an ADR and PR; the repository owner
is the final reviewer and merge authority. See [ADR 0019](docs/adr/0019-owner-reviewed-architecture-and-contributions.md).

Check the task's approved baseline before editing: inspected unpublished source
can differ from `main`. Component green means ready at its stated evidence level,
not that the application or release has been accepted. Source-derived architecture
PNGs use the same exact reviewed-hash gate as synthetic gallery images.

## Start here

Work happens on your own feature branch and reaches `main` only through a pull
request that the owner reviews and merges. The short workflow, branch and title
naming rules, task partitions, and review expectations are in
[the collaboration workflow](docs/collaboration-workflow.md). Read it before
picking up a task.

## Safe contribution checklist

Before staging a change:

- use only synthetic transcripts and reserved example identities;
- remove absolute machine paths, emails, usernames, hostnames, account IDs, private remotes, tokens, and screenshots; the sole exception is a visually reviewed synthetic gallery PNG at a fixed `docs/images/` filename, with a matching hash pin in `scripts/privacy_scan.py`;
- do not add databases, JSONL exports, model weights, caches, logs, or `.env` files;
- pin external model/package revisions and record their license/provenance;
- state whether every metric is provider-reported, deterministic, estimated, classifier-derived, or LLM-judged;
- include missing/unknown behavior and an abstention path;
- add tests for redaction and deletion when implementation begins.

Before committing:

```text
git status --short
git diff --cached --check
git diff --cached
git config --get user.email
```

The email printed by the final command will be public. Use a deliberate public/noreply identity.

The complete local and CI command set, including operating-system ownership of
the link and subprocess cleanup security tests, is documented in
[the CI quality gate](docs/ci-quality-gate.md).

## Fixtures

Fixtures must be obviously synthetic and must not be lightly edited copies of real conversations. Use reserved domains and example paths. Include synthetic secrets only when they are labeled canaries and guaranteed invalid.

## Metric proposals

Every new metric needs:

- a precise definition and unit;
- source events and missing-data behavior;
- task-type normalization, if applicable;
- expected value and known failure modes;
- privacy classification;
- validation method and minimum evidence;
- versioning and migration behavior;
- a statement of what the metric must not be used to infer.

Do not combine metrics into a universal prompt or developer score without a separate, reviewed design decision.
