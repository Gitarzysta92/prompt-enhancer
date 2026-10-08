# Claude Code instructions

This public repository analyzes highly sensitive coding-agent data. Follow `AGENTS.md` and the policies below for every task.

- Never read or commit real files from `~/.claude`, `~/.codex`, provider credentials, private repositories, or local transcript/database paths unless the user explicitly authorizes a narrowly scoped read-only diagnostic. Even then, never reproduce sensitive contents.
- Use synthetic examples only. Replace identities, hostnames, project names, paths, account IDs, remotes, and tokens with obvious reserved examples.
- Keep all ingestion read-only and prefer official SDK, app-server, hook, or OpenTelemetry surfaces. Isolate unstable transcript parsers behind version checks.
- No transcript text may leave the machine without explicit per-run consent, redaction, and a destination preview.
- Do not add employee rankings or a single prompt/developer quality score. Keep outcome evidence and uncertain model judgments visibly separate.
- Before any commit, inspect staged content and verify that Git uses a public/noreply email.
