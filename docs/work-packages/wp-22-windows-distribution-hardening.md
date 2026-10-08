# WP-22: Windows distribution and local-data hardening

Status: **design and synthetic test tranche planned; no supported binary release
or publisher infrastructure exists yet**

## Outcome

Prompt Enhancer should be installable per user on Windows 11, run without a
console or administrator rights, keep its private state outside roaming/cloud
folders, remain useful offline, and update only through signed artifacts. The
repository must be able to build and verify a deterministic staging tree before
the owner supplies a signing identity or release host.

This package does not change `SECURITY.md`’s current unsupported-release status.
It defines the code and evidence required before that statement may change.

## Packaging decision

- **Primary:** per-user MSIX delivered through a signed `.appinstaller` channel.
- **Secondary:** per-user WiX MSI for managed environments that cannot sideload
  MSIX.
- **Rejected:** NSIS custom scripts and a one-file PyInstaller executable.

The current pywebview/WebView2 desktop host remains. Windows 11 provides the
WebView2 runtime. The application stages a pinned CPython embeddable runtime so
existing isolated child processes can still execute `python -I script`; a
one-file freezer would make `sys.executable` point at the application launcher
and break that contract.

The base application excludes Torch, CUDA, model weights, and the optional
`models` extra. A separately signed and explicitly approved model-runtime pack
may be added only after its size, licenses, hashes, and cache destination are
shown to the user.

## Deterministic build stage

The mergeable build tooling will:

1. verify a pinned CPython embeddable archive by SHA-256;
2. install a hash-locked core + desktop dependency set with no dependency
   resolution during release;
3. build the frontend through `npm ci` and the committed lockfile;
4. copy packaged resources through one `importlib.resources` abstraction rather
   than repository-relative paths;
5. normalize timestamps and generate hash-based bytecode;
6. emit a per-file build manifest containing public tool versions, Git revision,
   lockfile hashes, and artifact hashes; and
7. build twice and compare manifests before release signing.

Unsigned developer packages are labelled not distributable. Release mode exits
non-zero unless signing and signature verification succeed.

## Installed resource paths

Repository-relative assumptions are removed from:

- dashboard static asset discovery;
- accelerator probe discovery;
- model cache/free-disk discovery; and
- future social quarantine/share roots.

The application home remains under local, non-roaming application data. Packaged
launch ignores development home/host/port overrides unless an explicit
development command is used. Every configurable private root rejects symlink and
Windows reparse-point components.

## Windows ACL boundary

POSIX mode bits are not a Windows access-control implementation. A platform port
hardens and verifies private directories/files. Its Windows adapter applies a
protected DACL granting only the current user and `SYSTEM`; tests inspect the
resulting ACL on Windows CI. The documented limit is explicit: administrators
and same-user malware remain outside this boundary.

The policy covers:

- analyzer, social, identity, billing, and job databases;
- secrets and key blobs;
- model cache and runtime packs;
- backups and export staging;
- WebView2 profile and local logs; and
- incoming-file quarantine and partial transfers.

## Local secret custody

API session tokens, pseudonym keys, and future device keys move behind a closed
credential-store port. The Windows development adapter uses user-scope DPAPI
with UI disabled and writes only encrypted blobs through the hardened path.

Plaintext migration is transactional: encrypt, persist, reload and verify before
the old file is overwritten and removed. The software does not claim protection
from another process already running as the same user. Portable backup of the
pseudonym key requires an explicit passphrase-protected export; normal data
exports omit secrets.

## Desktop service lifecycle

- The owned local service binds an ephemeral numeric loopback port.
- The chosen port is recorded in a hardened local file.
- Desktop HMAC challenge/response remains the primary identity proof.
- A Windows listener-owner check may additionally verify the PID, user SID, and
  signed installed image path.
- A per-user named mutex permits one active instance; a second launch requests
  focus rather than creating another listener.
- The service is not a Windows Service, creates no scheduled task, requires no
  elevation, and creates no firewall rule.
- Explicit opt-in launch-at-sign-in uses an HKCU entry removed by erase and
  uninstall.
- Closing or crashing the WebView tears down the owned server and model children.

No LAN listener is part of this package. Direct file transfer from WP-20 requires
its own later network-consent and firewall design.

## Backup, export, restore, and erase

A platform maintenance service owns a single inventory of every path the app may
create. Adding a path without an export/erase classification fails a test.

### Backup

- SQLite online backup API produces consistent database copies.
- A manifest records schema versions, application version, timestamps, and
  hashes.
- Restore rejects a newer schema and any hash mismatch.
- Sensitive portable backups require reviewed authenticated encryption and a
  user passphrase; no custom cipher is implemented.

### Export

- Data export uses allowlisted repository projections, never raw table dumps.
- Exports are labelled sensitive derived data.
- A destination likely to be cloud-synchronized produces a warning and requires
  explicit confirmation.

### Erase

- Stop workers and close databases first.
- Remove databases plus WAL/SHM files, secrets, web profile, logs, transfers,
  and local service metadata.
- Model cache deletion is a separate explicit choice because it may be large.
- Verify the inventory and synthetic canaries after deletion.
- Describe this as application-level deletion, not forensic media sanitization.

Local export and deletion remain available offline and after entitlement lapse.

## Incoming-file quarantine

Incoming names are display metadata only. The receiver generates internal part
and final names below a hardened per-transfer directory. The path layer rejects
absolute paths, `..`, symlinks, junctions/reparse points, alternate data streams,
reserved device names, trailing dots/spaces, and excessive length.

Quarantined files do not inherit executable permission, receive Windows
Mark-of-the-Web where supported, and are never implicitly opened. Transfer
integrity and recipient approval from WP-20 remain separate gates.

## Model runtime and cache

Every optional download binds model key, repository, immutable revision, license,
expected bytes, permitted file types, per-file hashes, and destination. The user
reviews licenses, size, network host, and the fact that the download host sees
their IP address.

Without an exact approval receipt, the application makes no network request.
Downloads remain anonymous, safetensors-only, `trust_remote_code=False`, size
bounded, hash verified, and atomically installed. Each model/cache is separately
deletable.

## Updates and rollback

MSIX/App Installer performs artifact download, signature verification,
installation, and rollback. The application does not implement a privileged
self-updater.

An optional in-app advisory fetches only a bounded, signed JSON manifest with
schema, channel, version, minimum supported version, artifact hash, publication
and expiry times, and notes URL. It sends no account, installation, device,
hardware, metric, or usage identifier. Stable/beta rollout is channel- and
time-based, not a hidden device cohort.

Tampered, expired, oversized, wrongly signed, or unapproved downgrade manifests
fail closed. With update checking disabled, no socket is opened.

## Logs, crashes, and diagnostics

The packaged application keeps access logging and telemetry disabled. Local
structured logs use a closed event-code vocabulary, bounded rotation, hardened
storage, and deterministic secret/PII/path redaction. Provider and I/O exception
text is never logged or returned to the UI.

There is no automatic crash upload. A diagnostic bundle is generated only on
request, locally redacted, and previewed before manual sharing. The WebView2
profile and any local crash artifacts remain inside the erase inventory.

## Offline and egress contract

Local analysis, metrics, history, task flow, local social history, export,
backup, restore, erase, and received files work without network access. The only
future egress classes are:

- an opt-out signed update advisory;
- an explicitly approved model/runtime download; and
- a separately approved WP-21 provider request.

An egress allowlist test and suite-wide non-loopback socket guard verify that no
other module opens a remote connection.

## SBOM, signing, and provenance

The build produces CycloneDX inventories for the staged Python and frontend
trees plus third-party notices, and includes them in the installer. The release
manifest binds toolchain and lockfile hashes.

Production signing requires an owner-controlled trusted signing service or
hardware-protected certificate, CI workload identity, timestamp policy, HTTPS
hosting, and signature verification. Certificates and private keys never enter
the repository. Code signing cannot guarantee a warning-free first launch; no
SmartScreen-clean claim is permitted.

## Release attack gates

1. A loopback squatter or foreign process cannot satisfy desktop identity proof.
2. Environment/configuration cannot produce a non-loopback packaged listener.
3. The whole test suite remains offline except explicitly allowlisted mocks.
4. Update manifests reject tamper, expiry, downgrade, key mismatch, and oversize.
5. Backup/restore rejects tamper and incompatible schema; secrets are excluded by
   default.
6. Erase canaries disappear from databases, WAL, secrets, profile, logs,
   quarantine, cache, temp paths, and launch metadata.
7. Plaintext-to-DPAPI migration never deletes before verified round-trip.
8. Quarantine rejects traversal, reparse points, ADS, device names, and execute
   paths and records Mark-of-the-Web where supported.
9. Model download makes no request without exact approval and rejects wrong hash,
   file type, size, revision, or license identity.
10. Synthetic email, key, token, account, hostname, path, prompt, and output
    canaries never reach logs, error bodies, manifests, SBOM examples, or UI.
11. Two independent staging builds have identical public build manifests.
12. The uninstall/erase inventory covers every application-created path.

## Owner-provided prerequisites

- Windows signing identity, publisher name, and timestamp policy;
- HTTPS release/model hosting and its retention/logging policy;
- Windows CI runners and signing workload identity;
- signed-update key custody and rollback runbook;
- EULA, privacy notice, third-party notices, and model/CUDA license review;
- private vulnerability reporting and incident-response process; and
- real Windows 11 verification of MSIX storage, ACLs, DPAPI migration, WebView2
  profile, update/rollback, SmartScreen behavior, and uninstall data handling.

Until these are independently verified, the repository may claim a tested build
pipeline—not a supported, production-ready installer.
