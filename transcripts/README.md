# AI agent transcripts

This project was built end to end in a single **Claude Code** session (Anthropic, model Claude Opus 5.5).

| File | What it is |
|---|---|
| `claude-code-session.md` | Readable rendering: every prompt, reply and tool call, with long tool outputs collapsed |
| `claude-code-session.jsonl` | The raw session export (Claude Code's export feature), one JSON record per line |

**Privacy redaction.** The only changes to the export are these. Personal email addresses and the names of unrelated personal files that appeared in a directory listing (ID documents, bank statements, CVs) are replaced with `[REDACTED-…]` markers. Screenshots are replaced with `[image removed for privacy]`. All prompts, reasoning, code and tool calls are otherwise unchanged.
