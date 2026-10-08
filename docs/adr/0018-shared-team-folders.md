# ADR 0018: Shared team folders - agents collaborating in one folder, peer to peer

- Status: accepted (2026-08-20); first slice implemented (share registry, p2p
  file surface, peer client, agent mounting) - LAN listener deferred
- Owner direction: teams should be able to collaborate through a shared
  folder instead of (or beside) git. A person explicitly allows sharing one
  folder; teammates connect to it directly, peer to peer, and their agents -
  the in-app local agent (ADR 0016), Codex, Claude Code, or any model they
  drive - work in that folder as a different mode of collaboration. Documents,
  notes and code move as files in a live folder rather than as commits.

## Context

The app already has a folder-scoped agent with per-call approvals (ADR 0016)
and a designed direct file-transfer lane with grants and audit
(`application/file_sharing`, served only where a social service exists). What
is missing is the *working folder* shape: one folder, several people, agents
from any side editing files, no central server in the data path.

## Decision

1. **Share registry (explicit, revocable).** Sharing a folder is an explicit
   act: `POST /v1/shared-folders {path, name}` registers the folder and
   returns a **share token once**; only the token's SHA-256 lands in
   `shared-folders.sqlite3` in the app home (same isolated-store pattern as
   the central annotation dataset). `DELETE` revokes; a revoked share answers
   401 immediately. The registry lists name, folder, created/revoked times
   and never the token.
2. **P2P surface.** Peers speak to `/p2p/v1/{share_id}/...` with
   `X-Share-Token`:
   - `GET manifest` - bounded file list (path, size, sha256, mtime), skip
     dirs shared with the agent workspace (`.git`, `node_modules`, ...);
   - `GET files/{path}` - one file's bytes (base64, size-capped);
   - `PUT files/{path}` - write with optimistic concurrency: the writer
     sends the hash of the version it based its edit on (`base_sha256`);
     on mismatch the write lands as `<name>.conflict-<peer>-<stamp><ext>`
     beside the original - both versions survive, like folder-sync tools,
     and nothing is silently lost. Paths resolve strictly inside the shared
     root; traversal is rejected.
   The surface is served by the same loopback app today. Binding it to a LAN
   address is a **separate, explicit opt-in** left to the next slice - it
   must never expose `/v1/*` (the app token) on that interface. Peer-to-peer
   here means the data path is machine-to-machine; the central/login server
   is never in it.
3. **Peer client ("join a folder").** The receiving side registers a peer
   link - URL + token + a local target folder - then `pull` mirrors changed
   files into the target (by hash) and `push` sends local edits back with
   `base_sha256` for conflict detection. The local target folder is then an
   ordinary agent workspace: point the in-app agent (or Codex, or Claude
   Code) at it and collaborate; `pull`/`push` are explicit actions in the
   first slice, not a background daemon.
4. **Consent and boundaries.** The share action names exactly one folder and
   is the consent to serve its contents to holders of that token; the join
   action names the peer URL before the first byte moves. Shared folders are
   working files the person chose - never the app's databases, transcripts
   or session stores; the app home cannot be shared. Every module that dials
   a peer is registered in the egress registry; the app's own listener stays
   loopback-only in this slice.
5. **Relation to git and to file_sharing.** This is a collaboration mode for
   live working sets - drafts, docs, agent output - not a history store; git
   remains the answer for versioned code. The social `file_sharing` lane
   (per-file grants, audit, quotas) stays the shape for one-off transfers to
   a person; shared folders are the shape for a *place* people and agents
   keep working in.

## Consequences

- A team can put a folder "on the table": one person shares, others join,
  everyone's agents read and write the same files with conflicts preserved
  as sibling copies.
- Verified end to end on this machine: share -> manifest -> pull into a
  second folder -> agent edits -> push -> conflict path exercised, over the
  real HTTP surface.
- The LAN listener, background sync, and per-peer write permissions are the
  next slices; the registry, wire format and conflict rules do not change
  for them.
