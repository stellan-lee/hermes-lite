"""Governance CLI for the Work Experience validation MVP.

This module deliberately stays outside the chat/slash-command surfaces.  It
opens the active profile's ``state.db`` lazily and delegates all persistence,
sanitization, lifecycle, and scope enforcement to ``agent.experience``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


logger = logging.getLogger(__name__)

_MODES = ("off", "capture", "shadow", "assist")
_MODE_RANK = {mode: index for index, mode in enumerate(_MODES)}
_EGRESS_POLICIES = (
    "local_only",
    "same_provider_trust_domain",
    "explicit_any_provider",
)
_SENSITIVITIES = ("normal", "private_repo", "local_only", "blocked")
_LESSON_STATUSES = (
    "candidate",
    "active",
    "disputed",
    "deprecated",
    "rejected",
    "retracted",
)
_LATEST_RETRIEVAL_UNAVAILABLE = object()

_PURGE_DISCLOSURE = (
    "Purge permanently removes this item and its dependent rows from the "
    "active state.db on a best-effort basis. It cannot erase copies already "
    "present in database backups, WAL history, filesystem snapshots, exported "
    "files, session transcripts, or model-provider logs."
)


def _state_db_path() -> Path:
    """Resolve the active profile path at command execution time."""

    from marlow_constants import get_marlow_home

    return Path(get_marlow_home()).expanduser().resolve() / "state.db"


def _profile_namespace() -> str:
    # Scope identifiers are intentionally profile-local.  The canonical home
    # path is never persisted as lesson content or sent to a provider.
    return str(_state_db_path().parent)


@contextmanager
def _open_store() -> Iterator[Any]:
    from agent.experience.store import ExperienceStore

    with ExperienceStore(_state_db_path()) as store:
        yield store


def _scope_resolver() -> Any:
    from agent.experience.scope import ScopeResolver

    return ScopeResolver(_profile_namespace())


def _policy_mode_flags(mode: str) -> tuple[bool, bool, bool, bool]:
    """Map the user-facing mode to independent, denied-by-default grants.

    Reflection is held false for the validation MVP even in capture mode.
    Enabling automatic retrospective generation requires a later, explicit
    product gate rather than being smuggled in through this CLI.
    """

    if mode == "off":
        return False, False, False, False
    if mode == "capture":
        return True, False, False, False
    if mode == "shadow":
        return True, True, False, False
    if mode == "assist":
        return True, True, True, False
    raise ValueError(f"unsupported experience mode: {mode}")


def _stored_policy_mode(policy: Any) -> str:
    if _field(policy, "recall_allowed", False) and _field(
        policy, "injection_allowed", False
    ):
        return "assist"
    if _field(policy, "recall_allowed", False):
        return "shadow"
    if _field(policy, "capture_allowed", False):
        return "capture"
    return "off"


def _effective_mode(policy: Any) -> tuple[str, str]:
    from marlow_cli.config import load_config

    configured = load_config().get("experience", {})
    global_mode = configured.get("mode", "off") if isinstance(configured, dict) else "off"
    if global_mode not in _MODES:
        return "off", "invalid global experience.mode"
    if global_mode == "off":
        return "off", "global experience.mode is off"
    capture_allowed = bool(_field(policy, "capture_allowed", False))
    recall_allowed = bool(_field(policy, "recall_allowed", False))
    injection_allowed = bool(_field(policy, "injection_allowed", False))
    if global_mode == "capture":
        if capture_allowed:
            return "capture", "global mode and project policy permit capture"
        return "off", "project policy does not permit experience capture"
    if not recall_allowed:
        if capture_allowed:
            return "capture", "project policy permits capture but not recall"
        return "off", "project policy does not permit experience recall"
    if global_mode == "shadow":
        return "shadow", "global mode and project policy permit recall"
    if not injection_allowed:
        return "shadow", "project policy does not permit injection"
    return "assist", "global mode and project policy permit injection"


def _policies(store: Any) -> Sequence[Any]:
    from agent.experience.models import LOCAL_OWNER_PRINCIPAL, ScopePolicy

    return [
        ScopePolicy(
            principal_id=row["principal_id"],
            repository_id=row["repository_id"],
            project_id=row["project_id"],
            project_root_rel=row["project_root_rel"],
            workspace_root=row.get("workspace_root"),
            capture_allowed=bool(row["capture_allowed"]),
            recall_allowed=bool(row.get("recall_allowed", False)),
            injection_allowed=bool(row["injection_allowed"]),
            reflection_allowed=bool(row["reflection_allowed"]),
            max_egress_policy=row["max_egress_policy"],
            updated_at=row["updated_at"],
        )
        for row in store.list_scope_policies(principal_id=LOCAL_OWNER_PRINCIPAL)
    ]


def _resolved_scope(store: Any, project_root: str | Path | None) -> Any:
    root = Path(project_root or os.getcwd()).expanduser()
    return _scope_resolver().resolve(root, _policies(store))


def _make_policy(args: argparse.Namespace) -> Any:
    # Resolve once against the caller's cwd. Passing a relative path twice to
    # ScopeResolver would otherwise discover from cwd but reinterpret the
    # project root relative to the Git toplevel.
    root = Path(args.project_root).expanduser().resolve()
    capture, recall, injection, reflection = _policy_mode_flags(args.mode)
    resolver = _scope_resolver()
    now = time.time()
    if resolver.discover_git(root) is not None:
        return resolver.make_git_policy(
            root,
            root,
            capture_allowed=capture,
            recall_allowed=recall,
            injection_allowed=injection,
            reflection_allowed=reflection,
            max_egress_policy=args.egress,
            updated_at=now,
        )
    return resolver.make_workspace_policy(
        root,
        capture_allowed=capture,
        recall_allowed=recall,
        injection_allowed=injection,
        reflection_allowed=reflection,
        max_egress_policy=args.egress,
        updated_at=now,
    )


def _promote_global_mode(requested_mode: str) -> None:
    """Raise the global rollout gate so a newly enabled project can run.

    Project policies remain the authorization boundary. The global mode is a
    maximum feature capability, so enabling one project may promote it but
    disabling or narrowing another project never silently downgrades peers.
    """

    current = _global_mode()
    if requested_mode == "off" or _MODE_RANK.get(current, -1) >= _MODE_RANK[requested_mode]:
        return
    from marlow_cli.config import ensure_marlow_home, get_config_path
    from utils import atomic_roundtrip_yaml_update

    ensure_marlow_home()
    atomic_roundtrip_yaml_update(
        get_config_path(),
        "experience.mode",
        requested_mode,
    )


def _cmd_policy_set(args: argparse.Namespace) -> int:
    policy = _make_policy(args)
    with _open_store() as store:
        saved = store.upsert_scope_policy(**_plain(policy))
    saved = saved or policy
    _promote_global_mode(args.mode)
    effective, reason = _effective_mode(saved)
    print(f"Experience policy saved for {Path(args.project_root).expanduser().resolve()}")
    print(f"  policy mode:   {_stored_policy_mode(saved)}")
    print(f"  egress:        {_enum_text(_field(saved, 'max_egress_policy'))}")
    print(f"  global mode:   {_global_mode()}")
    print(f"  effective:     {effective} ({reason})")
    return 0


def _cmd_policy_show(args: argparse.Namespace) -> int:
    with _open_store() as store:
        policies = list(_policies(store))
        if not policies:
            selected = []
        elif args.all:
            selected = policies
        else:
            selected = [_resolved_scope(store, args.project_root).policy]

    if not selected:
        print("No Work Experience project policies are configured.")
        return 0
    if args.json:
        payload = []
        for policy in selected:
            effective, reason = _effective_mode(policy)
            payload.append(
                {
                    "policy": _plain(policy),
                    "global_mode": _global_mode(),
                    "effective_mode": effective,
                    "effective_reason": reason,
                }
            )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    for index, policy in enumerate(selected):
        if index:
            print()
        effective, reason = _effective_mode(policy)
        root = _field(policy, "workspace_root") or _field(policy, "project_root_rel")
        print(f"Project:          {root}")
        print(f"Repository ID:    {_field(policy, 'repository_id')}")
        print(f"Project ID:       {_field(policy, 'project_id')}")
        print(f"Policy mode:      {_stored_policy_mode(policy)}")
        print(f"Capture allowed:  {_yes_no(_field(policy, 'capture_allowed', False))}")
        print(f"Recall allowed:   {_yes_no(_field(policy, 'recall_allowed', False))}")
        print(f"Injection allowed: {_yes_no(_field(policy, 'injection_allowed', False))}")
        print(f"Reflection:       {_yes_no(_field(policy, 'reflection_allowed', False))}")
        print(f"Max egress:       {_enum_text(_field(policy, 'max_egress_policy'))}")
        print(f"Effective mode:   {effective} ({reason})")
    return 0


def _global_mode() -> str:
    from marlow_cli.config import load_config

    experience = load_config().get("experience", {})
    return str(experience.get("mode", "off")) if isinstance(experience, dict) else "off"


def _tags(args: argparse.Namespace) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for attr, namespace in (
        ("task_type", "task_type"),
        ("technology", "technology"),
        ("entity", "entity"),
        ("failure", "failure"),
    ):
        for value in getattr(args, attr, ()) or ():
            values.append((namespace, value))
    return tuple(values)


def _cmd_add(args: argparse.Namespace) -> int:
    from agent.experience.models import CreatedBy, LessonBody

    body = LessonBody(
        applies_when=args.applies_when,
        does_not_apply_when=args.does_not_apply_when,
        guidance=args.guidance,
        rationale=args.rationale,
    )
    with _open_store() as store:
        resolved = _resolved_scope(store, args.project_root)
        scope = resolved.as_ref()
        lesson = store.create_lesson(
            principal_id=scope.principal_id,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            repository_id=scope.repository_id,
            project_id=scope.project_id,
            title=args.title,
            summary=args.summary,
            body=body,
            tags=_tags(args),
            confidence=getattr(args, "confidence", 0.6),
            sensitivity=args.sensitivity,
            egress_policy=args.egress,
            producer_trust_domain=args.producer_trust_domain,
            created_by=CreatedBy.USER,
        )
    print(f"Candidate lesson created: {_field(lesson, 'id')}")
    print("Approve it before it can enter normal recall.")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    with _open_store() as store:
        resolved = None if args.all_scopes else _resolved_scope(store, args.project_root)
        lessons = store.list_items(
            principal_id="local-owner",
            repository_id=None if resolved is None else resolved.repository_id,
            project_id=None if resolved is None else resolved.project_id,
            status=args.status,
            limit=args.limit,
        )
    if args.json:
        print(json.dumps([_plain(item) for item in lessons], indent=2, ensure_ascii=False))
        return 0
    if not lessons:
        print("No matching Work Experience lessons.")
        return 0
    for lesson in lessons:
        revision = _field(lesson, "revision", {})
        print(
            f"{_field(lesson, 'id')}  {_enum_text(_field(lesson, 'current_status')):<10} "
            f"r{_field(revision, 'revision', _field(lesson, 'current_revision', '?'))}  "
            f"{_field(revision, 'title', _field(lesson, 'title', ''))}"
        )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    with _open_store() as store:
        lesson = store.get_item(args.lesson_id, include_history=True)
    if lesson is None:
        raise LookupError("lesson not found")
    if args.json:
        print(json.dumps(_plain(lesson), indent=2, ensure_ascii=False))
    else:
        _print_lesson(lesson)
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    with _open_store() as store:
        lesson = store.approve_lesson(
            args.lesson_id,
            reason=args.reason or "approved by local owner",
            actor="user",
        )
    print(f"Lesson approved: {_field(lesson, 'id')} (active)")
    return 0


def _cmd_retract(args: argparse.Namespace) -> int:
    with _open_store() as store:
        lesson = store.retract_lesson(
            args.lesson_id,
            reason=args.reason,
            actor="user",
        )
    print(f"Lesson retracted: {_field(lesson, 'id')}")
    print("It is no longer eligible for retrieval.")
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    with _open_store() as store:
        lesson = store.get_item(args.lesson_id)
        if lesson is None:
            raise LookupError("lesson not found")
        current = _editable_document(lesson)
        direct = _direct_edit_document(args, current)
        edited = direct if direct is not None else _edit_json(current)
        if edited is None or edited == current:
            print("No changes; no revision created.")
            return 0
        previous_revision = int(_field(_field(lesson, "revision", {}), "revision", 0))
        body = _body_from_document(edited)
        revised = store.edit_lesson(
            args.lesson_id,
            title=edited["title"],
            summary=edited["summary"],
            body=body,
            tags=_tags_from_document(edited),
            editor="user",
            edit_reason=args.reason or "user edit",
        )
    revision = _field(_field(revised, "revision", {}), "revision", "?")
    if revision == previous_revision:
        print("No changes; no revision created.")
        return 0
    print(f"Lesson revised: {_field(revised, 'id')} (revision {revision})")
    return 0


def _cmd_purge(args: argparse.Namespace) -> int:
    print(_PURGE_DISCLOSURE)
    if not args.yes and not _confirm(f"Permanently purge {args.lesson_id}?"):
        print("Purge cancelled.")
        return 0
    with _open_store() as store:
        purge_result = store.purge_item(args.lesson_id)
    if not purge_result.get("purged"):
        raise LookupError("lesson not found")
    print(f"Purged {args.lesson_id} from the active experience database.")
    print("Historical copies outside the active database may still exist as disclosed above.")
    return 0


def _cmd_why_last(args: argparse.Namespace) -> int:
    with _open_store() as store:
        resolved = _resolved_scope(store, args.project_root)
        diagnostic = _get_latest_retrieval(
            store,
            principal_id=resolved.principal_id,
            repository_id=resolved.repository_id,
            project_id=resolved.project_id,
        )
    if diagnostic is _LATEST_RETRIEVAL_UNAVAILABLE:
        print("Latest recall diagnostics are not available in this Marlow build.")
        return 0
    if diagnostic is None:
        print("No Work Experience recall diagnostic exists for this project.")
        return 0
    if args.json:
        print(json.dumps(_plain(diagnostic), indent=2, ensure_ascii=False))
        return 0
    retrieval = _field(diagnostic, "retrieval", diagnostic)
    items = _field(diagnostic, "items", ()) or ()
    print(f"Candidate recall: {_field(retrieval, 'id')}")
    print(f"Created: {_field(retrieval, 'created_at')}")
    print(f"Provider trust domain: {_field(retrieval, 'provider_trust_domain', 'local/none')}")
    print(
        "Diagnostic only: this records ranked candidates, not proof that a "
        "lesson was injected, followed, or caused the outcome."
    )
    if not items:
        print("No lesson passed the recall filters.")
        return 0
    for item in items:
        reasons = ", ".join(_field(item, "match_reasons", ()) or ()) or "no match reasons recorded"
        print(
            f"  #{_field(item, 'rank', '?')} {_field(item, 'item_id')} "
            f"[{_enum_text(_field(item, 'disposition', 'retrieved'))}] score={_field(item, 'score', '?')}"
        )
        print(f"     why: {reasons}")
    return 0


def _get_latest_retrieval(store: Any, **scope: str) -> Any:
    """Read the latest diagnostic across compatible store revisions.

    The validation MVP's storage worker and CLI land independently. Keeping
    this tiny compatibility seam prevents governance commands from importing
    private SQL while the public diagnostic method name settles.
    """

    for name in ("get_latest_retrieval", "latest_retrieval"):
        method = getattr(store, name, None)
        if callable(method):
            return method(**scope)
    return _LATEST_RETRIEVAL_UNAVAILABLE


def _body_from_document(document: Mapping[str, Any]) -> Any:
    from agent.experience.models import LessonBody

    return LessonBody(
        applies_when=document["applies_when"],
        does_not_apply_when=document.get("does_not_apply_when") or None,
        guidance=document["guidance"],
        rationale=document["rationale"],
    )


def _tags_from_document(document: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    from agent.experience.models import TagNamespace

    result: list[tuple[str, str]] = []
    tags = document.get("tags", {})
    if not isinstance(tags, Mapping):
        raise ValueError("tags must be an object keyed by tag namespace")
    for namespace, values in tags.items():
        ns = TagNamespace(namespace)
        if not isinstance(values, list):
            raise ValueError(f"tags.{namespace} must be a list")
        result.extend((ns.value, value) for value in values)
    return tuple(result)


def _editable_document(lesson: Any) -> dict[str, Any]:
    revision = _field(lesson, "revision")
    body = _field(revision, "body")
    tags: dict[str, list[str]] = {}
    for tag in _field(revision, "tags", ()) or ():
        tags.setdefault(_enum_text(_field(tag, "namespace")), []).append(_field(tag, "value"))
    return {
        "title": _field(revision, "title"),
        "summary": _field(revision, "summary"),
        "applies_when": _field(body, "applies_when"),
        "does_not_apply_when": _field(body, "does_not_apply_when"),
        "guidance": _field(body, "guidance"),
        "rationale": _field(body, "rationale"),
        "tags": tags,
    }


def _direct_edit_document(
    args: argparse.Namespace, current: Mapping[str, Any]
) -> dict[str, Any] | None:
    field_names = (
        "title",
        "summary",
        "applies_when",
        "does_not_apply_when",
        "guidance",
        "rationale",
    )
    if not any(getattr(args, name, None) is not None for name in field_names):
        return None
    result = dict(current)
    for name in field_names:
        value = getattr(args, name, None)
        if value is not None:
            result[name] = value
    return result


def _edit_json(initial: Mapping[str, Any]) -> dict[str, Any] | None:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(initial, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            path = handle.name
        command = [*shlex.split(editor), path]
        if not command:
            raise ValueError("EDITOR is empty")
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise RuntimeError("editor exited without saving a valid revision")
        with open(path, encoding="utf-8") as handle:
            edited = json.load(handle)
        if not isinstance(edited, dict):
            raise ValueError("edited lesson must be a JSON object")
        return edited
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("could not read the edited lesson JSON") from exc
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _print_lesson(lesson: Any) -> None:
    revision = _field(lesson, "revision")
    body = _field(revision, "body")
    print(f"{_field(lesson, 'id')}  [{_enum_text(_field(lesson, 'current_status'))}]")
    print(f"Title: {_field(revision, 'title')}")
    print(f"Summary: {_field(revision, 'summary')}")
    print(f"Revision: {_field(revision, 'revision')}")
    print(f"Applies when: {_field(body, 'applies_when')}")
    if _field(body, "does_not_apply_when"):
        print(f"Does not apply when: {_field(body, 'does_not_apply_when')}")
    print(f"Guidance: {_field(body, 'guidance')}")
    print(f"Rationale: {_field(body, 'rationale')}")
    tags = _field(revision, "tags", ()) or ()
    if tags:
        print(
            "Tags: "
            + ", ".join(
                f"{_enum_text(_field(tag, 'namespace'))}={_field(tag, 'value')}"
                for tag in tags
            )
        )
    print(f"Scope: {_enum_text(_field(lesson, 'scope_type'))}")
    print(f"Sensitivity: {_enum_text(_field(lesson, 'sensitivity'))}")
    print(f"Egress: {_enum_text(_field(lesson, 'egress_policy'))}")


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_text(value: Any) -> str:
    scalar = value.value if isinstance(value, Enum) else value
    return "" if scalar is None else str(scalar)


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _confidence(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def _safe_error(exc: Exception) -> str:
    # Experience exceptions contain bounded, payload-free validation text.
    # Unexpected storage/provider errors can contain SQL or user content and
    # are intentionally collapsed to a generic message.
    module = exc.__class__.__module__
    if module.startswith("agent.experience") or isinstance(exc, (ValueError, LookupError)):
        try:
            from agent.experience.safety import sanitize_for_return

            return sanitize_for_return(str(exc))[:500]
        except Exception:
            return "the experience request was rejected by validation"
    return "the experience operation failed safely; no changes were applied"


def _dispatch(handler: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], None]:
    def run(args: argparse.Namespace) -> None:
        try:
            code = handler(args)
        except Exception as exc:
            # Exception messages may carry user-authored lesson content or
            # SQLite fragments. Keep logs payload-free just like stdout.
            logger.debug(
                "experience CLI operation failed (%s)",
                exc.__class__.__name__,
            )
            print(f"experience: {_safe_error(exc)}")
            raise SystemExit(2) from None
        if code:
            raise SystemExit(code)

    return run


def _add_content_arguments(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument("--title", required=required, help="Short lesson title")
    parser.add_argument("--summary", required=required, help="Concise lesson summary")
    parser.add_argument(
        "--applies-when", required=required, help="Conditions where the lesson applies"
    )
    parser.add_argument(
        "--does-not-apply-when", help="Conditions or exceptions where it must not be used"
    )
    parser.add_argument("--guidance", required=required, help="Behavior to use in future work")
    parser.add_argument("--rationale", required=required, help="Evidence-based reason for the guidance")


def register_cli(parent: argparse.ArgumentParser) -> None:
    """Attach ``marlow experience`` governance commands to *parent*."""

    parent.set_defaults(func=lambda _args: parent.print_help())
    commands = parent.add_subparsers(dest="experience_command", metavar="COMMAND")

    policy = commands.add_parser("policy", help="Manage project scope and consent policy")
    policy.set_defaults(func=lambda _args: policy.print_help())
    policy_commands = policy.add_subparsers(dest="experience_policy_command", metavar="COMMAND")

    policy_set = policy_commands.add_parser("set", help="Create or replace a project policy")
    policy_set.add_argument(
        "--project-root", required=True, help="Explicit Git project or non-Git workspace root"
    )
    policy_set.add_argument("--mode", required=True, choices=_MODES)
    policy_set.add_argument(
        "--egress", choices=_EGRESS_POLICIES, default="local_only",
        help="Maximum provider egress permitted by this project policy",
    )
    policy_set.set_defaults(func=_dispatch(_cmd_policy_set))

    policy_show = policy_commands.add_parser("show", help="Show the effective project policy")
    policy_show.add_argument("--project-root", help="Directory inside the configured project")
    policy_show.add_argument("--all", action="store_true", help="Show every configured policy")
    policy_show.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    policy_show.set_defaults(func=_dispatch(_cmd_policy_show))

    add = commands.add_parser("add", help="Add a user-authored candidate lesson")
    add.add_argument("--project-root", help="Directory inside the configured project")
    _add_content_arguments(add, required=True)
    add.add_argument("--task-type", action="append", default=[])
    add.add_argument("--technology", action="append", default=[])
    add.add_argument("--entity", action="append", default=[])
    add.add_argument("--failure", action="append", default=[], help="Normalized failure fingerprint")
    add.add_argument(
        "--confidence",
        type=_confidence,
        default=0.6,
        help="Initial evidence confidence for this manual lesson (default: 0.6)",
    )
    add.add_argument("--sensitivity", choices=_SENSITIVITIES, default="local_only")
    add.add_argument("--egress", choices=_EGRESS_POLICIES, default="local_only")
    add.add_argument("--producer-trust-domain")
    add.set_defaults(func=_dispatch(_cmd_add))

    list_parser = commands.add_parser("list", help="List lessons in the current project")
    list_parser.add_argument("--project-root", help="Directory inside the configured project")
    list_parser.add_argument("--all-scopes", action="store_true", help="List lessons across this profile")
    list_parser.add_argument("--status", action="append", choices=_LESSON_STATUSES)
    list_parser.add_argument("--limit", type=_positive_int, default=100)
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=_dispatch(_cmd_list))

    show = commands.add_parser("show", help="Show one lesson, including its content")
    show.add_argument("lesson_id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=_dispatch(_cmd_show))

    approve = commands.add_parser("approve", help="Activate a candidate lesson")
    approve.add_argument("lesson_id")
    approve.add_argument("--reason")
    approve.set_defaults(func=_dispatch(_cmd_approve))

    edit = commands.add_parser("edit", help="Append an immutable lesson revision")
    edit.add_argument("lesson_id")
    edit.add_argument("--reason")
    _add_content_arguments(edit, required=False)
    edit.set_defaults(func=_dispatch(_cmd_edit))

    retract = commands.add_parser("retract", help="Remove a lesson from behavioral use")
    retract.add_argument("lesson_id")
    retract.add_argument("--reason", required=True)
    retract.set_defaults(func=_dispatch(_cmd_retract))

    purge = commands.add_parser("purge", help="Best-effort permanent deletion from active state.db")
    purge.add_argument("lesson_id")
    purge.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation")
    purge.set_defaults(func=_dispatch(_cmd_purge))

    delete = commands.add_parser(
        "delete",
        help="Compatibility alias for `purge`; requires the explicit --purge flag",
    )
    delete.add_argument("lesson_id")
    delete.add_argument(
        "--purge",
        action="store_true",
        required=True,
        help="Confirm that best-effort physical deletion, not retraction, is intended",
    )
    delete.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation")
    delete.set_defaults(func=_dispatch(_cmd_purge))

    why = commands.add_parser("why", help="Explain the latest recall decision")
    why.add_argument("--last", action="store_true", required=True)
    why.add_argument("--project-root", help="Directory inside the configured project")
    why.add_argument("--json", action="store_true")
    why.set_defaults(func=_dispatch(_cmd_why_last))

    why_last = commands.add_parser("why-last", help="Alias for `experience why --last`")
    why_last.add_argument("--project-root", help="Directory inside the configured project")
    why_last.add_argument("--json", action="store_true")
    why_last.set_defaults(func=_dispatch(_cmd_why_last), last=True)
