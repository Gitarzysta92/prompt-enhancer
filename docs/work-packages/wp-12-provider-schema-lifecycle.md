# WP-12: Offline provider-schema lifecycle

- Status: Foundational offline gate implemented; provider-specific acquisition jobs deferred
- Decision: [ADR 0003](../adr/0003-offline-provider-schema-compatibility-lifecycle.md)
- Depends on: provider adapter contracts, synthetic privacy fixtures, release review

## Outcome

Provider schema changes become explicit compatibility releases rather than runtime
self-modification. The current slice adds a dependency-free, content-free manifest
validator and a synthetic example. It does not inspect an installed Codex, Claude
Code, or Cursor application and does not change live adapter selection.

## Implemented slice

- strict manifest version and closed field vocabulary;
- exact provider-version tuples, with no ranges or wildcard support;
- separate schema family, adapter, decoder, canonical model, and fixture versions;
- capability states of supported, partial, or unsupported;
- verified, experimental, and blocked release states;
- verified-release gates for official provenance, synthetic contracts, privacy
  review, and a content-free local smoke attestation;
- bounded single-file parsing with duplicate-key rejection and sanitized results;
- no provider process, network, session discovery, response hashing, cache access,
  adapter download, or automatic merge; and
- synthetic CLI and privacy tests.

Validate a reviewed manifest offline:

```powershell
python scripts/check_provider_compatibility_manifest.py tests/fixtures/synthetic/providers/compatibility-manifest-v1.json
```

Check one exact compatibility tuple:

```powershell
python scripts/check_provider_compatibility_manifest.py `
  tests/fixtures/synthetic/providers/compatibility-manifest-v1.json `
  --provider example_agent `
  --surface catalog `
  --schema-family example.catalog.v1 `
  --provider-version example-1.0 `
  --capability session_list
```

Only `compatibility_supported` exits successfully for a support query. Experimental,
partial, blocked, unknown-family, untested-version, and unsupported-capability
results fail the release gate without echoing input values.

## Next provider-specific packages

1. Export the reviewed in-application decoder registry into this manifest shape
   without adding provider access to the CLI.
2. Add a quarantined official-artifact acquisition workflow and an offline diff job
   for each provider surface; neither job may contain user data or release authority.
3. Create a new immutable decoder family and synthetic fixture corpus when a
   semantic schema change is accepted.
4. Add capability-aware dashboard status: supported, partial, untested, or blocked.
5. Implement Claude only against a pinned documented interface. Select Cursor's
   documented source in a separate ADR before registering it.

## Acceptance checks

- focused CLI tests and the repository privacy scan pass;
- old family fixtures remain passing when a new family is added;
- an unknown conversation variant cannot produce a complete prompt-quality claim;
- verified entries cannot rely on synthetic contracts alone;
- no real provider response, configuration, installed version, path, identifier, or
  compatibility probe output is committed; and
- automation may prepare review material but cannot activate or publish a decoder.
