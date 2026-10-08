# Privacy design policy

Status: design-stage policy, 2026-08-06. The software does not yet implement these guarantees.

Prompt Enhancer will process data that can contain private source code, credentials, personal messages, customer data, health or financial information, filesystem paths, organization identifiers, and confidential business decisions. “Local cache” does not mean “safe data.” Provider transcripts can contain everything a tool read or printed.

## Default data tiers

| Tier | Stored data | Default | Purpose |
|---|---|---:|---|
| 0 | Provider availability, version, session counts, date ranges, byte sizes | On after consented discovery | Let the user choose a scope without reading content |
| 1 | Content-free event metadata, consented private display labels, and derived operational metrics | On for selected scopes | Local navigation, time, tokens, tool reliability, compaction, verification flow |
| 2 | Locally redacted prompt/message text and embeddings | Off | Prompt and conversation analytics |
| 3 | Encrypted raw content vault | Off | Re-analysis, audit, and improved redaction |
| 4 | Redacted content sent to a named remote model | Off, per-run approval | Optional deep rubric analysis |

The user selects providers, projects, date ranges, and tiers. Discovery must not silently escalate from metadata to content.
Codex display labels are a narrow Tier 1 exception to content-free persistence:
only the final working-directory component and the explicit `thread.name` value may
be retained after `local-history` consent. They are sensitive local data, not
anonymous metadata. Full paths and `preview` text remain prohibited, and labels
must not enter logs, exports, or remote payloads. Public fixtures may use only fictional labels.


## Data minimization invariants

- Do not ingest credentials, provider auth/config files, debug logs, unrelated caches, file-history snapshots, or full home directories.
- Canonicalize and allowlist every source path; reject symlink, junction, or reparse-point escapes.
- Strip emails, account IDs, hostnames, absolute paths, workspace paths, remotes, and installation IDs at the ingestion boundary unless a metric strictly requires a pseudonym. The consented display-label exception above never permits a full path.
- Use an installation-specific keyed HMAC for stable pseudonyms. Unsalted hashes are not sufficient for predictable paths, emails, or repository names.
- Redact secrets and PII before logs, embedding, export, crash reporting, or remote analysis. Any explicitly consented sensitive local field must have a documented purpose, bounded schema, private storage, and no implicit egress.
- Store raw content separately from metrics. Encrypt optional raw content with an application key held by the operating-system credential store.
- Treat embeddings and summaries as sensitive because they can preserve or reveal source facts.
- Never collect application analytics about the user's prompts or source code. Operational telemetry for Prompt Enhancer itself must be off by default and content-free if introduced.

## Local does not mean no egress

The dashboard may run entirely on the user's machine, but Codex and Claude normally contact their model providers. If a user exposes metrics through MCP and asks a model to analyze them, the returned database content enters that provider's model context. The UI must disclose this before enabling MCP content access.

Remote analysis requires all of the following:

1. a named destination provider and model;
2. the fields and approximate volume to be sent;
3. local secret/PII redaction;
4. a preview or summary of the outgoing payload;
5. explicit user approval or an explicit saved organization policy;
6. recorded model, rubric, redaction, and consent-policy versions.

No “enterprise” label should be treated as proof of zero retention. Retention and training terms vary by account, provider, and configuration.

## Retention and deletion

- Tier 0/1 metrics: user-configurable retention; indefinite local retention may be useful for trends.
- Tier 2 redacted content: short default retention, proposed 30 days.
- Tier 3 raw vault: disabled by default; proposed 7-day default when enabled.
- Exports: explicit, user-selected, and visibly marked with their sensitivity tier.
- Deletion must work by provider, project pseudonym, session, and date range and cascade to embeddings, summaries, caches, model results, and aggregates.
- Source provider files are immutable to Prompt Enhancer. Deleting imported data must never delete the original Codex or Claude session.

## Team use

The first safe team design is engineer-local processing with upload of content-free aggregates. Team views should:

- avoid individual leaderboards and employee-performance scoring;
- use minimum cohort sizes and suppress small groups;
- separate adoption, outcome, reliability, and workload dimensions;
- disclose metric definitions, missingness, and uncertainty;
- allow contributors to inspect and delete their own data where policy permits;
- never infer personality, intelligence, intent, health, or protected traits.

Sentiment and emotion are private coaching signals, not competence measures.

## Public repository policy

Only synthetic content may be committed. Reserved examples should use values such as `person@example.invalid`, `/home/example/project`, `C:\Users\Example\project`, `example.invalid`, and clearly fake tokens like `example_token_do_not_use`.

`.gitignore` is defense in depth; it does not make tracked or force-added content safe. Staged changes and commit metadata must be reviewed before every public push.

Public screenshots are prohibited by default. A synthetic gallery capture is
allowed only after visual review when it uses a fixed `docs/images/` filename,
contains the scanner's metadata-free PNG envelope, and exactly matches its
hardcoded SHA-256 pin. The exception is not a directory allowlist and does not
permit private screenshots, arbitrary images, or image metadata.
