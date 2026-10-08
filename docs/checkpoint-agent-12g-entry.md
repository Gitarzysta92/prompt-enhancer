# Checkpoint Agent-12g entry: localhost Windows folder chooser

Date: 2026-09-01

This checkpoint repairs the New session workspace field after owner review
showed that the ordinary loopback browser still required a pasted absolute
path. A standard web directory input cannot disclose the selected absolute
Windows path to the local Python service, so it cannot open an existing
workspace in place without copying or uploading it.

## Frozen owner-visible contract

1. The ordinary authenticated `127.0.0.1` Agent page exposes `Browse…` without
   requiring a model or an already-created session.
2. One click opens the Windows folder chooser in the existing local app
   process. It starts no PowerShell, command shell, terminal or helper process.
3. Only a valid browser session with an exact same-origin request and CSRF
   proof may open the dialog. API-token and bearer clients are rejected.
4. Selecting a folder returns only its absolute path and fills the workspace
   field. It does not create a session, start a model, scan the directory, read
   files or grant write, command, web or approval authority.
5. Cancel preserves the current field. A concurrent request reports `busy`;
   malformed, unsupported and exception paths fail closed to manual entry.
6. The owned desktop bridge remains the preferred path when present. If that
   bridge becomes unavailable, the same-origin local chooser is the fallback.
7. The UI-only endpoint remains outside the provider-neutral Agent-controller
   discovery contract and does not change its native-approval boundary.
8. Automated validation never opens a real dialog. The physical folder click
   remains an explicit owner check after the rebuilt page is left ready.

## Required evidence

1. Picker unit tests cover capability, selection, cancel, invalid output,
   exception redaction and one-dialog concurrency.
2. Assembled HTTP tests cover unauthenticated, wrong-origin, missing-CSRF,
   token-client and valid-browser requests plus private cache headers.
3. Strict frontend transport tests reject extra keys, inconsistent capability
   tuples and relative paths.
4. Agent component tests cover browser selection, cancel, busy, no session
   creation and native-bridge fallback.
5. Production build, generated API check, privacy scan, compilation and a
   content-free live loopback reload pass with one listener and no visible
   terminal or model process.
