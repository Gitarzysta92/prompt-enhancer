# Repository instructions for coding agents

This is a public, privacy-sensitive repository for local coding-agent analytics.

## Non-negotiable privacy rules

- Never copy, stage, commit, print, summarize, or upload real Codex or Claude sessions, prompts, tool output, source snippets, account data, or local configuration.
- Never read provider credential files such as Codex `auth.json`, Claude `.claude.json`, keychains, environment files, or unrelated home-directory content.
- Use only synthetic fixtures with fictional identities, repositories, paths, tokens, and conversations.
- Do not include usernames, personal email addresses, hostnames, account IDs, absolute home paths, private remotes, or screenshots in code, tests, logs, issues, or documentation.
- Do not send transcript content to a network service or remote model without an explicit task-specific user instruction and a redaction preview.
- Treat embeddings, summaries, labels, and aggregate metrics as sensitive derived data; pseudonymized is not anonymous.
- Bind local services to loopback by default. Do not add remote listening, unrestricted SQL, or raw-transcript MCP tools.

## Implementation rules

- Prefer documented provider interfaces. Raw JSONL and internal SQLite parsing must be isolated, version-gated compatibility adapters.
- Ingestion adapters are read-only. They must not delete, archive, resume, rename, or mutate provider sessions.
- Missing values remain unknown. Never silently convert missing token usage, duration, cost, or task outcome to zero or failure.
- Record provenance and versions for provider, adapter, metric definition, redactor, model, tokenizer, prompt/rubric, and schema.
- Objective verification evidence outranks inferred text scores. Never treat an assistant's completion claim as proof of task success.
- Keep prompt, outcome, efficiency, affect, and safety dimensions separate. Do not create a developer ranking or universal “intelligence” score.
- Pin model revisions and licenses; do not vendor model weights. Keep `trust_remote_code` disabled and prefer safetensors or ONNX.
- New fixtures must pass secret/PII canary tests and contain only reserved example values.

## Before committing

- Inspect `git diff --cached` and `git status --short`.
- Confirm the commit email is a public/noreply identity.
- Run the repository's tests and privacy/secret scanner once those commands exist.
- Do not bypass a safety test to make CI pass.
