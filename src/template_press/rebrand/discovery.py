"""Discover a target repo's identity — the VALIDATOR, never the authority.

Per OQ3 (decision log 2026-06-15): the committed source-config is the
authoritative FROM identity; discovery cross-checks it against the target
(pyproject [project].name / authors, the [project.scripts] key, git origin,
src-vs-flat layout) and the CLI fails loudly on any mismatch. This replaces
the silent half-rebrand failure mode (EMPIRICAL R2) with a hard stop.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 — reads git origin of the target
import tomllib
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from template_press.rebrand.cargo_manifest import CargoFacts, read_cargo_facts
from template_press.rebrand.config import toml_string
from template_press.rebrand.identity import (
    CARGO_IDENT_PREFIX,
    CARGO_NAME_RE,
    CARGO_ROLE_RE,
    PYTHON_IDENTIFIER_RE,
    Identity,
    cargo_ident,
    occurs,
    token_occurs,
)
from template_press.rebrand.inventory import (
    capture_surface_snapshot,
    rewrite_surface_texts,
    tracked_path_strings,
)
from template_press.rebrand.languages import KNOWN_LANGUAGES, SUPPORTED_LANGUAGES
from template_press.rebrand.node_manifest import (
    NodeManifest,
    read_node_manifest,
    unscoped,
)
from template_press.rebrand.pathing import ROOT_CONTROL
from template_press.rebrand.rules import regenerate_suggestion
from template_press.rebrand.safety import git_hardening_args, scrubbed_git_env
from template_press.rebrand.substitutions import (
    cargo_path_splits,
    identity_row_rewriter,
)

if TYPE_CHECKING:
    from template_press.rebrand.rules import Rules

# What Cargo accepts as a package or target name, which is wider than the
# cargo_names value regex: a maturin library is commonly `_name`.
_CARGO_USABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_ORIGIN_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class Discovered:
    package_name: str | None
    app_name: str | None  # FIRST [project.scripts] key, for display/back-compat
    owner: str | None
    repo_name: str | None
    author: str | None
    email: str | None
    layout: str | None  # "src" | "flat" | None
    app_names: tuple[str, ...] = ()  # ALL [project.scripts] keys, insertion order
    # The first checked language in KNOWN_LANGUAGES order, or None. It selects
    # the source-config proposal. When python is not checked, the fatal-check
    # fields above stay None.
    source_kind: str | None = None
    # package.json was checked: the manifest values below feed the two
    # declared-field checks and the non-fatal warnings.
    node_checked: bool = False
    npm_name: str | None = None
    cli_names: tuple[str, ...] = ()  # package.json bin keys, manifest order
    manifest_package_name: str | None = None  # derived from npm_name
    manifest_author: str | None = None
    manifest_email: str | None = None
    manifest_owner: str | None = None  # package.json repository, never origin
    manifest_repo_name: str | None = None
    named_cli_names: tuple[str, ...] = ()  # object-form bin keys only
    cargo: CargoFacts | None = None  # set only when rust is a checked language


def _origin(target: Path) -> tuple[str | None, str | None]:
    # A config read on an untrusted target (its .git/config is attacker
    # input) — scrubbed env blocks a poisoned global config from redirecting
    # this; hardening args are cheap insurance even though this is not a
    # working-tree read.
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        [  # noqa: S607
            "git",
            "-C",
            str(target),
            *git_hardening_args(),
            "remote",
            "get-url",
            "origin",
        ],
        capture_output=True,
        text=True,
        env=scrubbed_git_env(),
    )
    if result.returncode != 0:
        return None, None
    m = _ORIGIN_RE.match(result.stdout.strip())
    return (m["owner"], m["repo"]) if m else (None, None)


def _python_project(target: Path) -> dict[str, Any] | None:
    """The ``[project]`` table of the root ``pyproject.toml``, if it has one."""
    pyproject_path = target / "pyproject.toml"
    if not pyproject_path.is_file():
        return None
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8")).get("project")
    return project if isinstance(project, dict) else None


def discover(
    target: Path,
    languages: Sequence[str] | None = None,
    ignored: Collection[str] = (),
) -> Discovered:
    """Read identity from the manifests of ``languages``.

    The CLI passes the language guard's ``LanguageDecision.checked`` and the
    names in its ``ignored``. An ignored manifest is never read. When neither
    python nor node is checked, every other readable manifest is read, so a
    ``package.json`` without ``name`` keeps its declared-field checks.
    """
    package_name = app_name = author = email = None
    app_names: tuple[str, ...] = ()
    selected = SUPPORTED_LANGUAGES.intersection(languages or ())
    narrowed = selected - {"rust"}

    def reads(language: str) -> bool:
        return language not in ignored and (not narrowed or language in narrowed)

    project = _python_project(target) if reads("python") else None
    manifest = read_node_manifest(target) if reads("node") else None
    checked = selected or {
        language
        for language, value in (("python", project), ("node", manifest))
        if value is not None
    }
    first_checked = next((name for name in KNOWN_LANGUAGES if name in checked), None)
    source_kind = "cargo" if first_checked == "rust" else first_checked
    cargo = read_cargo_facts(target) if "rust" in selected else None
    if project is not None:
        raw_name = project.get("name")
        if isinstance(raw_name, str):
            package_name = raw_name.replace("-", "_")
        scripts = project.get("scripts", {})
        if isinstance(scripts, dict) and scripts:
            app_names = tuple(str(k) for k in scripts)
            app_name = app_names[0]  # first key — display/back-compat
        authors = project.get("authors", [])
        if isinstance(authors, list) and authors and isinstance(authors[0], dict):
            author = authors[0].get("name")
            email = authors[0].get("email")
    owner, repo_name = _origin(target)
    layout: str | None = None
    if package_name is not None:
        if (target / "src" / package_name).is_dir():
            layout = "src"
        elif (target / package_name).is_dir():
            layout = "flat"
    found = Discovered(
        package_name=package_name,
        app_name=app_name,
        owner=owner,
        repo_name=repo_name,
        author=author,
        email=email,
        layout=layout,
        app_names=app_names,
        source_kind=source_kind,
        cargo=cargo,
    )
    if manifest is None:
        return found
    return replace(
        found,
        node_checked=True,
        npm_name=manifest.name,
        cli_names=manifest.bins,
        named_cli_names=manifest.named_bins,
        manifest_package_name=(
            unscoped(manifest.name).replace("-", "_") if manifest.name else None
        ),
        manifest_author=manifest.author,
        manifest_email=manifest.email,
        manifest_owner=manifest.owner,
        manifest_repo_name=manifest.repo_name,
    )


def node_proposal(
    manifest: NodeManifest, owner: str | None, repo_name: str | None
) -> dict[str, str | None]:
    """Propose source-config values from ``package.json``; gaps stay ``None``.

    ``owner`` and ``repo_name`` arrive already resolved (git origin first, the
    manifest ``repository`` only as a fallback). Nothing absent is guessed.
    """
    name = manifest.name
    package_name = unscoped(name).replace("-", "_") if name else None
    app_name: str | None = None
    cli_name: str | None = None
    if manifest.bins:
        first = manifest.bins[0]
        if PYTHON_IDENTIFIER_RE.fullmatch(first):
            app_name = first
        elif "-" in first:
            app_name = first.replace("-", "_")
            # A string-form bin has no key: its command follows the package name.
            cli_name = first if first in manifest.named_bins else None
        else:
            app_name = first  # not derivable: validation rejects it cleanly
    return {
        "package_name": package_name,
        "repo_name": repo_name,
        "app_name": app_name,
        "author": manifest.author,
        "email": manifest.email,
        "owner": owner,
        "npm_name": name if name not in (None, repo_name, package_name) else None,
        "cli_name": cli_name,
    }


def cargo_role_table(facts: CargoFacts) -> dict[str, str]:
    """One role per name, keyed by its lowercase underscore form.

    Leading underscores are dropped from the key, since a role starts with a letter.

    Spellings of one name share a role. ``facts.names`` is sorted, so a hyphen
    spelling (``-`` sorts before ``_``) is the value that role records.
    """
    table: dict[str, str] = {}
    seen: set[str] = set()
    for name in facts.names:
        ident = cargo_ident(name)
        if ident in seen:
            continue
        seen.add(ident)
        # A role must start with a letter, so ``_acme_widget`` keys as ``acme_widget``.
        base = role = ident.lower().lstrip("_")
        suffix = 2
        while role in table:
            role = f"{base}_{suffix}"
            suffix += 1
        table[role] = name
    return table


def _unloadable_names(facts: CargoFacts) -> list[str]:
    """Names a ``cargo_names`` table cannot hold under its validators."""
    return [
        name
        for role, name in sorted(cargo_role_table(facts).items())
        if not (CARGO_ROLE_RE.fullmatch(role) and CARGO_NAME_RE.fullmatch(name))
    ]


def _table_limit(names: Sequence[str]) -> str:
    return (
        f"A cargo_names table cannot represent {list(names)!r}: its values must "
        f"match {CARGO_NAME_RE.pattern} and its roles {CARGO_ROLE_RE.pattern}. "
        "Choose identity fields whose rewrite "
        "keeps the package and Rust spellings of that name consistent, or "
        "rename it."
    )


def cargo_table_hint(facts: CargoFacts) -> str:
    """A paste-ready ``cargo_names`` table, or why no loadable table exists."""
    unloadable = _unloadable_names(facts)
    if unloadable:
        return _table_limit(unloadable)
    rows = [
        f"{role} = {toml_string(name)}"
        for role, name in sorted(cargo_role_table(facts).items())
    ]
    return "\n".join(
        [
            "# press/press-source.toml",
            "[identity.cargo_names]",
            *rows,
            "",
            "# press-answers.toml: replace each value with the new crate name",
            "[answers.cargo_names]",
            *rows,
        ]
    )


def cargo_proposal(
    facts: CargoFacts, owner: str | None, repo_name: str | None
) -> dict[str, str | None]:
    """Propose source-config values from Cargo facts; gaps stay ``None``.

    Git origin wins; ``package.repository`` is used only when origin is absent.
    ``app_name`` is the underscore form of the first binary in ``facts.bins``
    (sorted order), or ``package_name`` for a library-only crate.
    """
    if owner is None and facts.repository is not None:
        match = _ORIGIN_RE.match(facts.repository)
        if match is not None:
            owner, repo_name = match["owner"], match["repo"]
    package_name = cargo_ident(facts.primary) if facts.primary else None
    return {
        "package_name": package_name,
        "repo_name": repo_name,
        "app_name": cargo_ident(facts.bins[0]) if facts.bins else package_name,
        "author": facts.author,
        "email": facts.email,
        "owner": owner,
    }


def _unmapped_name_is_related(
    name: str, changing: dict[str, str], rules: Rules
) -> bool:
    return any(
        occurs(spelling, field, value, rules.substring_rewrite_fields)
        for spelling in {name, cargo_ident(name)}
        for field, value in changing.items()
    )


def _changing_values(source: Identity, dest: Identity | None) -> dict[str, str]:
    """Source values this press changes; every value when ``dest`` is unknown."""
    wanted = dest.as_dict() if dest is not None else None
    return {
        field: value
        for field, value in source.as_dict().items()
        if wanted is None or wanted.get(field) != value
    }


def _identifier_on_surface(target: Path, ident: str, rules: Rules) -> bool:
    """Whether a file the press keeps names the crate by its Rust identifier."""
    removed_dirs = tuple(f"{rule.dir}/" for rule in rules.remove_dirs)
    return any(
        token_occurs(text, f"{CARGO_IDENT_PREFIX}crate", ident)
        for path, _where, text in rewrite_surface_texts(
            target,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
            skip_paths=frozenset(rule.file for rule in rules.remove),
        )
        if not path.startswith(removed_dirs)
    )


def _unmapped_name_is_broken(
    name: str,
    target: Path,
    rewrite: Callable[[str], str],
    changing: dict[str, str],
    rules: Rules,
) -> bool:
    """Whether the press's own rows would leave ``name`` inconsistent."""
    if name in rules.keep_names or not _unmapped_name_is_related(name, changing, rules):
        return False
    ident = cargo_ident(name)
    new_name, new_ident = rewrite(name), rewrite(ident)
    if (new_name, new_ident) == (name, ident):
        return False
    if not _CARGO_USABLE_RE.fullmatch(new_name):
        return True
    if cargo_ident(new_name) == new_ident:
        return False
    if new_name == name:
        return True  # the identifier moved and the package spelling did not
    # The package moved without its identifier, which matters only where code
    # names the crate (`acme_widget::hi()`).
    return _identifier_on_surface(target, ident, rules)


def _declared_path_problems(
    target: Path, source: Identity, dest: Identity, rules: Rules
) -> list[str]:
    return [
        f"cargo paths: {split}."
        for split in cargo_path_splits(target, source, dest, rules)
    ]


def _undeclared_lock_problem(target: Path, rules: Rules) -> str | None:
    """Refuse a tracked root ``Cargo.lock`` that no ``[[regenerate]]`` rebuilds."""
    if any(rule.file == "Cargo.lock" for rule in rules.regenerate):
        return None
    if "Cargo.lock" not in tracked_path_strings(capture_surface_snapshot(target)):
        return None
    return (
        "cargo_names: tracked Cargo.lock has no [[regenerate]] declaration, so "
        "it would keep the source crate names. Add this block to "
        "press/press-rules.toml (press does not run it; review the command "
        "first):\n" + (regenerate_suggestion("Cargo.lock") or "")
    )


# Strict, reserved, and 2018+ keywords. A crate so named can only be spelled
# ``r#name`` in code (``self``, ``super``, ``crate``, ``Self`` not even that).
_RUST_KEYWORDS = frozenset(
    "as async await break const continue crate dyn else enum extern false fn for "
    "gen if impl in let loop match mod move mut pub ref return self Self static "
    "struct super trait true try type unsafe use where while abstract become box "
    "do final macro override priv typeof unsized virtual yield".split()
)


def cargo_problems(
    target: Path, source: Identity, dest: Identity | None, rules: Rules
) -> list[str]:
    """Fatal Cargo checks. The no-table refusal needs a real ``dest``.

    Call only when rust is a checked language. Spellings are compared by
    underscore form, because Cargo treats ``[lib] name = "acme_core"`` as the
    default library of package ``acme-core``.
    """
    facts = read_cargo_facts(target)
    moved = None if dest is None else identity_row_rewriter(source, dest, target, rules)
    if moved is not None:
        keywords = sorted(
            ({cargo_ident(moved(name)) for name in facts.names} & _RUST_KEYWORDS)
            - {cargo_ident(name) for name in facts.names}
        )
        if keywords:
            return [
                f"cargo_names: the press would name a crate {keywords!r}, a Rust "
                "keyword that code can only spell as a raw identifier, which the "
                "press does not write. Choose another name"
            ]
    if not source.cargo_names:
        if dest is None or moved is None:
            return []
        rewrite = moved
        changing = _changing_values(source, dest)
        broken = [
            name
            for name in facts.names
            if _unmapped_name_is_broken(name, target, rewrite, changing, rules)
        ]
        if not broken:
            return _declared_path_problems(target, source, dest, rules)
        remedy = "" if _unloadable_names(facts) else "Declare the table:\n"
        return [
            f"cargo_names: the identity rows would rewrite crate name(s) "
            f"{broken!r} inconsistently, so the press would leave a broken "
            f"crate name. {remedy}{cargo_table_hint(facts)}"
        ]
    declared = {cargo_ident(name) for _role, name in source.cargo_names}
    out: list[str] = []
    lock_problem = _undeclared_lock_problem(target, rules)
    if lock_problem is not None:
        out.append(lock_problem)
    discovered = {cargo_ident(name) for name in facts.names}
    undeclared = [n for n in facts.names if cargo_ident(n) not in declared]
    if undeclared:
        out.append(
            f"cargo_names: target declares Cargo name(s) {undeclared!r} that are "
            "not source cargo_names values; add a role for each (a name that "
            "must not change uses the same value in both files)"
        )
        unloadable = [n for n in undeclared if not CARGO_NAME_RE.fullmatch(n)]
        if unloadable:
            out.append(f"cargo_names: {_table_limit(unloadable)}")
    if moved is not None:
        exact = {name for _role, name in source.cargo_names}
        respelled = [
            name
            for name in facts.names
            if "-" in name
            and name not in exact
            and cargo_ident(name) in declared
            and cargo_ident(moved(name)) != moved(cargo_ident(name))
        ]
        if respelled:
            out.append(
                f"cargo_names: target names {respelled!r} with a hyphen, but the "
                "matching role values have none, so the press would rename the "
                "crate's Rust identifier without its package name; declare each "
                "role with the hyphenated name"
            )
    missing = [n for _r, n in source.cargo_names if cargo_ident(n) not in discovered]
    if missing:
        out.append(
            f"cargo_names: source-config declares {missing!r} but no Cargo "
            "manifest contains that name"
        )
    third_party = [
        name for name in facts.external_dependencies if cargo_ident(name) in declared
    ]
    if third_party:
        out.append(
            f"cargo_names: non-local dependency {third_party!r} resolves to a "
            "declared source name; rewriting it would point at a different "
            "registry crate"
        )
    if dest is not None:
        destinations = {cargo_ident(name) for _role, name in dest.cargo_names}
        collisions = [
            name
            for name in facts.external_dependencies
            if cargo_ident(name) in destinations - declared
        ]
        if collisions:
            out.append(
                f"cargo_names: non-local dependency {collisions!r} has the same "
                "name as a destination crate, so Cargo could not tell them "
                "apart after the press; choose another destination name"
            )
        if not out:
            out = _declared_path_problems(target, source, dest, rules)
    return out


def cargo_warnings(
    target: Path, source: Identity, rules: Rules, dest: Identity | None = None
) -> list[str]:
    """One stderr line per name a table-less press leaves unchanged."""
    if source.cargo_names:
        return []
    facts = read_cargo_facts(target)
    values = _changing_values(source, dest)
    return [
        f"warning: cargo name {name!r} is not rewritten: it is "
        + (
            "listed in keep_names"
            if name in rules.keep_names
            else "unrelated to the changing identity"
        )
        for name in facts.names
        if name in rules.keep_names
        or not _unmapped_name_is_related(name, values, rules)
    ]


def mismatches(source: Identity, found: Discovered) -> list[str]:
    """Non-empty means the source-config does NOT describe this target."""
    out: list[str] = []
    checks: tuple[tuple[str, str | None], ...] = (
        ("package_name", found.package_name),
        ("owner", found.owner),
        ("repo_name", found.repo_name),
        ("author", found.author),
        ("email", found.email),
    )
    declared = source.as_dict()
    for field_name, discovered_value in checks:
        if discovered_value is None:
            continue  # undiscoverable field — config stands unchallenged
        if discovered_value != declared[field_name]:
            out.append(
                f"{field_name}: source-config says "
                f"{declared[field_name]!r} but target shows "
                f"{discovered_value!r}"
            )
    # app_name matches when it is ANY [project.scripts] key (membership),
    # not just the first (F3/D2) — a target may expose several scripts and
    # commit a non-first one. Empty app_names -> undiscoverable, unchallenged.
    if found.app_names and declared["app_name"] not in found.app_names:
        out.append(
            f"app_name: source-config says {declared['app_name']!r} but "
            f"target [project.scripts] exposes {list(found.app_names)!r}"
        )
    if found.node_checked:
        out.extend(_node_mismatches(declared, found))
    if (
        found.source_kind == "python"
        and found.package_name is not None
        and found.layout is None
    ):
        out.append(
            f"layout: pyproject declares {found.package_name!r} but neither "
            f"src/{found.package_name}/ nor {found.package_name}/ exists"
        )
    return out


def _node_mismatches(declared: dict[str, str], found: Discovered) -> list[str]:
    """The only fatal manifest checks: a DECLARED npm_name or cli_name."""
    out: list[str] = []
    npm_name = declared.get("npm_name")
    if npm_name is not None and found.npm_name not in (None, npm_name):
        out.append(
            f"npm_name: source-config says {npm_name!r} but package.json "
            f"name is {found.npm_name!r}"
        )
    cli_name = declared.get("cli_name")
    if cli_name is not None and found.cli_names and cli_name not in found.cli_names:
        out.append(
            f"cli_name: source-config says {cli_name!r} but package.json "
            f"bin exposes {list(found.cli_names)!r}"
        )
    return out


def manifest_warnings(source: Identity, found: Discovered) -> list[str]:
    """Non-fatal package.json disagreements, one stderr line each."""
    if not found.node_checked:
        return []
    declared = source.as_dict()
    out: list[str] = []

    def warn(field_name: str, expected: str, actual: str | None, where: str) -> None:
        if actual is not None and actual != expected:
            out.append(
                f"warning: {field_name}: source-config says {expected!r} "
                f"but {where} shows {actual!r}"
            )

    warn(
        "package_name",
        source.package_name,
        found.manifest_package_name,
        "package.json name",
    )
    warn("author", source.author, found.manifest_author, "package.json author")
    warn("email", source.email, found.manifest_email, "package.json author")
    if found.cli_names and declared.get("cli_name") is None:
        if source.app_name not in found.cli_names:
            out.append(
                f"warning: app_name: source-config says {source.app_name!r} "
                f"but package.json bin exposes {list(found.cli_names)!r}"
            )
    # The repository value is compared with origin when origin exists, else
    # with the source-config; it never feeds a fatal check.
    owner = found.owner if found.owner is not None else source.owner
    repo = found.repo_name if found.repo_name is not None else source.repo_name
    warn("owner", owner, found.manifest_owner, "package.json repository")
    warn("repo_name", repo, found.manifest_repo_name, "package.json repository")
    return out
