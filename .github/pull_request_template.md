## Summary

Describe the change and the evidence used to verify it.

For a trivial documentation fix, this section, the task link, and the privacy checklist are enough; skip the sections marked "code and behavior changes".

## Task

Task: #<issue number> (use `Refs`, not a closing keyword; the owner updates status and closes the task).

## Scope and non-goals (code and behavior changes)

- In scope:
- Not in scope:

## Acceptance proof (code and behavior changes)

Map each acceptance criterion from the task to the test, command, or synthetic fixture that shows it.

Evidence level (pick the highest actually reached, all with synthetic data): not verified / static review only / unit / integration / browser / packaged / native or real-model (owner-run) / clean-machine (owner-run)

Contributors do not need or use private provider sessions for any level. Owner inspection of private data does not replace native or install acceptance.

## Compatibility and recovery (code and behavior changes)

State what existing behavior, data, API, or schema is unchanged, and how to revert this change. Write "none" if nothing is affected.

## Privacy and safety checklist

- [ ] All examples and fixtures are synthetic; none are transformed real conversations.
- [ ] No prompt, transcript, private source, tool output, database, model weight/cache, screenshot, or telemetry export is included.
- [ ] No personal email, username, hostname, absolute home path, account ID, private remote, credential, or valid token is included.
- [ ] New metrics identify their source, missing-data behavior, version, validation, privacy tier, and prohibited interpretations.
- [ ] New models/dependencies pin a revision/version and document license and provenance.
- [ ] Redaction, deletion, and unknown/abstention paths are tested where relevant.
- [ ] I inspected the full staged diff and am using a deliberate public/noreply commit email.

## Validation

List tests, privacy canaries, benchmarks, and manual checks run.
