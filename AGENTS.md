# Agent Instructions

## Package Manager

Use **uv**: `uv sync`, `uv run <script>`

## Task Runner

Use **mise**: `mise run <task>` — see `mise.toml` for available tasks.

## Commit Attribution

AI commits MUST include:

```
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Do not commit unless explicitly asked.

## Superpowers

This project uses the [Superpowers](https://github.com/ejfox/superpowers) skill system.

- **Plans:** `.superpowers/plans/` — implementation plans go here
- **Memory:** `.superpowers/memory/` — persistent memory index at `.superpowers/memory/MEMORY.md`

When saving memories, write files to `.superpowers/memory/` and update `.superpowers/memory/MEMORY.md`.
When writing or referencing plans, use `.superpowers/plans/`.
