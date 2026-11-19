# Security Policy

## Supported versions

The project is in alpha; only the latest `main` is supported.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Report privately via
GitHub's "Report a vulnerability" (Security → Advisories) or by contacting the
maintainers listed in the repository profile. Include:

- affected version / commit,
- reproduction steps,
- impact (data exposure, command execution, permission bypass, ...).

We aim to acknowledge within 72 hours and to publish a fix and advisory for
confirmed issues.

## Threat model

WeChat Agent AI connects three untrusted surfaces:

1. **Chat content** — messages from other people are data, never instructions.
   The permission guard and the system prompt both assume prompt injection.
2. **The LLM** — it can request any tool, but every call is checked locally
   against the user's permission config; dangerous tools are denied by default.
3. **The Android device** — reached only through the `llmadb` CLI, never by
   constructing raw adb/shell strings from model output. `shell` is a
   separately gated dangerous tool.

Secrets (API Key) live in the per-user settings file and are never written to
the repository. Chat history stays in local SQLite unless the user exports it.

## Out of scope

- WeChat account bans or restrictions caused by automation (see docs/risks.md).
- Vulnerabilities in llm-adb, the MCP SDK or PySide6 itself; report them upstream.
