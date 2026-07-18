# Marlow Project Rename

## Goal

Rename every project-owned use of the former product name to Marlow, including
Python and TypeScript modules, public commands, environment variables, runtime
paths, packaging metadata, service names, tests, documentation, and generated
project artifacts.

## Canonical Mapping

| Previous casing | New casing |
| --- | --- |
| lowercase product token | `marlow` |
| title-case product token | `Marlow` |
| uppercase product token | `MARLOW` |

Project-owned compound identifiers follow the same mapping (for example,
`marlow_cli`, `MarlowCLI`, `MARLOW_HOME`, and `.marlow`). No compatibility
aliases using the previous product token are retained because the requested
outcome is a complete rename.

## Boundaries

Third-party proper nouns and immutable external identifiers are not renamed.
Examples include Meta's `hermes-parser` / `hermes-estree` npm packages and Nous
Research model IDs containing `hermes-3` or `hermes-4`. Changing those strings
would point Marlow at nonexistent dependencies or models.

The enclosing local worktree directory is managed by Codex and Git rather than
being a tracked project item, so this change only renames tracked repository
content beneath that directory.

## Implementation

1. Apply a case-preserving replacement to tracked text files.
2. Rename tracked files and directories from deepest path to shallowest path.
3. Restore only verified third-party identifiers.
4. Regenerate lock/build metadata where repository tooling supports it.
5. Repair imports and references exposed by tests and builds.

## Validation

- Search tracked paths for project-owned instances of the previous name.
- Search tracked text and classify any remaining matches as third-party names.
- Compile Python sources and run rename-sensitive Python tests.
- Type-check, test, and build the TUI/web packages that were renamed.
- Build Python distribution metadata when the local environment supports it.
- Review the final diff for accidental third-party renames and stale paths.
