# Learnings

## [LRN-20260717-001] best_practice

**Logged**: 2026-07-17T00:00:00+08:00
**Priority**: medium
**Status**: promoted
**Area**: backend

### Summary

Validate fallible runtime configuration before opening persistent resources.

### Details

The cleanup's first implementation opened the session database before model
and API-key validation. If agent construction failed, Python never entered the
CLI context manager and the connection remained open. A full-diff lifecycle
review caught this even though behavior tests passed.

### Suggested Action

Construct stateless validated dependencies first. Wrap later resource creation
and selection in cleanup-on-failure logic.

### Metadata

- Source: error
- Related Files: cli.py
- Tags: lifecycle, sqlite, review

**Promoted**: AGENTS.md engineering workflow requires lifecycle and full-diff review.

---

## [LRN-20260717-002] knowledge_gap

**Logged**: 2026-07-17T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary

Modern setuptools expects `project.license` to be an SPDX string.

### Details

The first clean build succeeded but warned that the older TOML table form,
`license = { text = "MIT" }`, will stop being supported after 2027-02-18.

### Suggested Action

Use `license = "MIT"` and declare `license-files = ["LICENSE"]`.

### Metadata

- Source: error
- Related Files: pyproject.toml
- Tags: packaging, setuptools, deprecation

### Resolution

- **Resolved**: 2026-07-17T00:00:00+08:00
- **Notes**: Updated the project metadata before final package validation.

---
