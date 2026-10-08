# Converge-07b.3 handoff — read-only MSIX package preflight

Status: **standalone read-only preflight implementation and automated validation
complete.** This slice verifies a supplied package against already authenticated
release metadata and an explicit signer pin. It is not connected to the
sidebar's staged-update action and does not make application installation or
production self-update available.

Date: 2026-09-05
Scope: bounded offline MSIX identity, digest/size and signer-pin preflight;
synthetic evidence only.

## What this slice closes

- `MsixPackageExpectation` requires an explicit package name, publisher,
  architecture and signer leaf SHA-256 pin. `X.Y.Z` release metadata maps only
  to the exact MSIX version `X.Y.Z.0`.
- `AuthenticatedReleaseArtifact.from_accepted(...)` is a validated DTO boundary:
  it derives package hash, size and release version only from an accepted update
  verification, but is not independently a cryptographic proof. The CLI first
  authenticates raw metadata with Ed25519; other callers must perform the same
  authentication before using the DTO. Unknown or invalid signed metadata
  remains rejected before package access.
- `MsixPackagePreflight` is read-only and returns a typed, content-free result.
  Signature-invalid, signature-unverifiable and signer-pin mismatch outcomes
  remain distinct. Every result has `can_install=false`; no extraction,
  installation, relaunch or UI/sidebar wiring is present.
- Package paths are refused before opening or invoking the signer when they are
  relative, traversing, UNC/device/drive-relative, ADS-like, reserved,
  control-character or otherwise Windows-ambiguous. ZIP central-directory
  bounds are checked before `ZipFile` parsing; ZIP64/bundles, MSI files and
  other unsupported package shapes fail closed. The preflight accepts only an
  ordinary `.msix` ZIP and keeps each member within the conservative 64 MiB
  bound.
- The manifest parser requires UTF-8 MSIX XML, the documented AppX namespace
  and one matching `Identity`. DTD/entity declarations, malformed XML,
  duplicate or ambiguous members, traversal/ADS/reserved names and
  file-directory collisions are rejected. Parent/leaf metadata is checked
  before and after reading; this is not an atomic filesystem snapshot or a
  proof against a same-user attacker race.
- The production native signer boundary is cache-only/read-only and has no UI
  or install action: missing trust
  chain or revocation evidence is an unknown/unverifiable failure, not proof of
  universal offline acceptance. The API choices follow Microsoft's
  [`WinVerifyTrust`](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-winverifytrust)
  and [`WINTRUST_DATA`](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/ns-wintrust-wintrust_data)
  documentation, including explicit state cleanup; package identity follows
  Microsoft's [Appx Identity schema](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-identity).

## Sanitized release-tool shape

Release tooling accepts only owner-supplied trusted inputs out of band. A
synthetic invocation shape is:

```text
uv run python scripts/verify_msix_package.py --package <synthetic-msix-path> --manifest <synthetic-manifest-path> --signature <synthetic-signature-path> --key-id <reserved-key-id> --public-key-hex <reserved-ed25519-public-key-hex> --installed-version <synthetic-installed-version> --channel stable --package-name <synthetic-package-name> --publisher <owner-supplied-publisher> --architecture x64 --signer-sha256 <reserved-signer-sha256>
```

Placeholders above are not configured release identities or usable credentials.
No public release host, certificate store, signing key or publisher identity is
stored in this repository. Production CLI use requires native verification;
injected signer doubles are limited to tests and the composition seam.

## Focused evidence

`tests/test_application_update_07b3_acceptance.py` passes **53/53** with
temporary synthetic packages, manifests, signatures and signer doubles. It
covers positive DTO/preflight composition, bad metadata signatures, identity /
version / architecture / digest / size binding, signer pinning and unknown
signer outcomes, unsafe paths before I/O, bounded ZIP central directories and
forged ZIP64/EOCD data, XML and archive hostility, model validation bypasses,
content-free CLI results, and the `can_install=false` invariant.

The final root-owned combined C07b.3 gate is **336 passed, 2 Windows
symlink-fixture skips and 1 intentionally deselected native smoke** in 17.21s
across the selected 17-file scope. The focused 53-case file, 15 CLI/non-native
regressions and 31 fake-native cases are overlapping subsets of that total, not
additional counts. Privacy scanning, `git diff --check` and the explicit
whitespace check for the seven new code/test files passed. No frontend, build,
API-schema, browser or app-reload gate was rerun for this standalone tool slice.

A separate real-Windows unsigned-container smoke failed closed: the native
VERIFY step reported an unsupported container, CLOSE returned successfully
without a Python exception, and the final typed result was
`PackageSignerUnavailable`. This is fail-closed smoke evidence only—not
unsigned-valid acceptance, native cleanup-failure evidence, or publisher/signing
proof. The owner-signed positive native acceptance remains unrun.

## Explicit non-claims and next gate

No package was extracted, installed, relaunched or downloaded. The preflight
tool is not connected to the application sidebar or `artifact.staged`; it
does not claim a usable updater, a 100% production update path or a configured
public release. Native publisher/signing/MSIX positive acceptance, installer
handoff, restart/recovery and rollback remain open under C07. The active remote
session restriction continues to prohibit PC/app restart, relaunch and install
until explicit owner approval.

All tests and tools under validation used temporary synthetic fixtures and made
no network egress, model/provider access or real home/configuration reads.

Recommended next bounded checkpoint: **C07b.4** connects the preflight result to
the staged-update review UI while keeping `can_apply=false`; no PC/app restart,
relaunch or install is permitted until separately authorized.
