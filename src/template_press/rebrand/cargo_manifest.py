"""Read the identity-bearing facts of a target's Cargo manifests.

The manifests are attacker-controlled input (they ship inside the target), so
every file is read as a regular, non-symlinked UTF-8 file and every workspace
member is checked for containment before it is read. A manifest that is
malformed, symlinked, or outside the target root raises ``ValidationError``.
Names are kept exactly as authored; hyphens are never normalized.
"""

from __future__ import annotations

import json
import os
import posixpath
import shutil
import subprocess  # nosec B404 — read-only offline `cargo metadata --no-deps`
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.safety import (
    SafetyError,
    assert_under_root,
    read_regular_nofollow,
)

_MANIFEST = "Cargo.toml"
_CARGO_METADATA_TIMEOUT_S = 30
_CARGO_ENV_BASE: tuple[str, ...] = (
    ("PATH", "SystemRoot", "PATHEXT", "USERPROFILE", "TEMP", "TMP")
    if os.name == "nt"
    else ("PATH", "HOME", "LANG", "TMPDIR")
)
_CARGO_ENV_TOOLCHAIN: tuple[str, ...] = (
    "CARGO_HOME",
    "RUSTUP_HOME",
    "RUSTUP_TOOLCHAIN",
)
# Cargo before edition 2024 also reads the underscore spellings. Reading both
# tables when a manifest has both only adds checks.
_DEPENDENCY_SECTIONS = (
    "dependencies",
    "dev-dependencies",
    "build-dependencies",
    "dev_dependencies",
    "build_dependencies",
)
_TARGET_SECTIONS = ("bin", "test", "example", "bench")
_LIB_KINDS = frozenset({"lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro"})
_INFERRED_DIRS = {
    "bin": "src/bin",
    "test": "tests",
    "example": "examples",
    "bench": "benches",
}
_TARGET_SHAPES = ("{}.rs", "{}/main.rs")
TARGET_AUTO_FLAGS: dict[str, str] = {
    "bin": "autobins",
    "test": "autotests",
    "example": "autoexamples",
    "bench": "autobenches",
}
_GLOB_CHARS = frozenset("*?[")
# A longer author entry is undiscoverable, never truncated into a guess.
_AUTHOR_MAX_CHARS = 1024

Table = dict[str, object]


@dataclass(frozen=True)
class CargoTarget:
    """One compilation target reported by ``cargo metadata``."""

    name: str
    kinds: tuple[str, ...]
    src_path: str  # target-root-relative POSIX path, preserving leaf symlinks
    edition: str | None = None


@dataclass(frozen=True)
class CargoPackageMetadata:
    """One package reported by ``cargo metadata --format-version 1 --no-deps``."""

    name: str
    manifest_path: str  # target-root-relative POSIX path
    targets: tuple[CargoTarget, ...]
    edition: str | None = None


@dataclass(frozen=True)
class CargoMetadata:
    """Validated ``cargo metadata --format-version 1 --no-deps`` result."""

    packages: tuple[CargoPackageMetadata, ...]
    workspace_members: frozenset[str]  # manifest_paths of workspace members


@dataclass(frozen=True)
class CargoFacts:
    names: tuple[str, ...]  # package, lib, and bin names, sorted, unique
    packages: tuple[str, ...]  # package names in manifest order
    bins: tuple[str, ...]  # sorted, unique
    primary: str | None  # root package; None for a virtual manifest
    author: str | None
    email: str | None
    repository: str | None
    external_dependencies: tuple[str, ...]  # resolved package names, non-local


@dataclass(frozen=True)
class DeclaredPath:
    """One path string a manifest declares, relative to that manifest."""

    kind: Literal["member", "exclude", "dependency", "target", "build", "workspace"]
    key: str  # where it is declared, for messages
    value: str

    @property
    def is_glob(self) -> bool:
        return self.kind == "member" and bool(_GLOB_CHARS & set(self.value))


def _table(value: object) -> Table:
    return value if isinstance(value, dict) else {}


def package_table(data: Table) -> Table:
    """Return ``[package]`` or Cargo's legacy ``[project]`` table."""
    if isinstance(pkg := data.get("package"), dict):
        return pkg
    if isinstance(proj := data.get("project"), dict):
        return proj
    return {}


def _package_section_name(data: Table) -> str:
    return "package" if isinstance(data.get("package"), dict) else "project"


def effective_edition(
    data: Table,
    workspace_package: Table | None = None,
    *,
    edition_override: str | None = None,
) -> str:
    """Cargo edition of one manifest, resolving ``edition.workspace = true``."""
    if edition_override:
        return edition_override.strip() or "2015"
    pkg = package_table(data)
    raw = _inherited_or_own(pkg, workspace_package or {}, "edition")
    return raw.strip() if isinstance(raw, str) and raw.strip() else "2015"


def workspace_package_for_manifest(
    target: Path,
    manifest: str,
    parsed: Table,
    loaded: Mapping[str, Table] | None = None,
) -> Table:
    """Resolve ``[workspace.package]`` for ``manifest``'s own workspace.

    Checks ``[package].workspace`` first, then a ``[workspace]`` table in
    ``manifest`` itself, then the nearest ancestor ``Cargo.toml`` inside
    ``target`` that declares ``[workspace]``.
    """
    cache = loaded or {}
    root = target.resolve()

    def _read_ws_pkg(rel_manifest: str) -> Table | None:
        norm = posixpath.normpath(rel_manifest)
        if norm == ".." or norm.startswith("../") or posixpath.isabs(norm):
            return None
        data = cache.get(norm)
        if data is None:
            candidate = root / norm
            try:
                assert_under_root(candidate, root)
                raw = read_regular_nofollow(candidate).decode("utf-8")
                data = tomllib.loads(raw)
            except (
                OSError,
                SafetyError,
                UnicodeDecodeError,
                tomllib.TOMLDecodeError,
            ):
                return None
        ws = data.get("workspace")
        if isinstance(ws, dict):
            return _table(ws.get("package"))
        return None

    manifest_dir = posixpath.dirname(manifest)
    ws_rel = package_table(parsed).get("workspace")
    if isinstance(ws_rel, str) and ws_rel.strip():
        explicit = posixpath.normpath(
            posixpath.join(manifest_dir, ws_rel.replace("\\", "/"), _MANIFEST)
        )
        found = _read_ws_pkg(explicit)
        if found is not None:
            return found
    if isinstance(parsed.get("workspace"), dict):
        return _table(_table(parsed.get("workspace")).get("package"))

    current = manifest_dir
    while True:
        parent = posixpath.dirname(current)
        if parent == current:
            break
        current = parent
        candidate_rel = posixpath.join(current, _MANIFEST) if current else _MANIFEST
        found = _read_ws_pkg(candidate_rel)
        if found is not None:
            return found
    return {}


def auto_discovery_enabled(
    data: Table,
    section: str,
    workspace_package: Table | None = None,
    *,
    edition_override: str | None = None,
) -> bool:
    """Whether Cargo auto-discovers ``[[<section>]]`` targets for ``data``.

    Honors explicit ``auto*`` booleans and Cargo's edition-2015 rule where
    declaring any ``[[<section>]]`` table disables auto-discovery unless the
    matching ``auto*`` flag is explicitly ``true``.
    """
    pkg = package_table(data)
    if not pkg:
        return False
    flag = pkg.get(TARGET_AUTO_FLAGS[section])
    if flag is False:
        return False
    if flag is True:
        return True
    if (
        effective_edition(data, workspace_package, edition_override=edition_override)
        == "2015"
    ):
        entries = data.get(section)
        if isinstance(entries, list) and any(isinstance(e, dict) for e in entries):
            return False
    return True


def _cargo_metadata_env() -> dict[str, str]:
    """Minimal offline environment for read-only ``cargo metadata``."""
    env: dict[str, str] = {}
    for name in (*_CARGO_ENV_BASE, *_CARGO_ENV_TOOLCHAIN):
        if name in os.environ:
            env[name] = os.environ[name]
    env["CARGO_NET_OFFLINE"] = "true"
    env["CARGO_TERM_COLOR"] = "never"
    return env


def _rel_under_root(raw_path: str, root: Path) -> str | None:
    """Convert a Cargo path to a ``root``-relative POSIX path without resolving
    leaf symlinks; return ``None`` if outside ``root``."""
    if not raw_path:
        return None
    cleaned = raw_path[4:] if raw_path.startswith("\\\\?\\") else raw_path
    norm = os.path.normpath(cleaned)
    try:
        rel = os.path.relpath(norm, str(root))
    except ValueError:
        return None
    if rel == "." or rel == os.pardir or rel.startswith(f"{os.pardir}{os.sep}"):
        return None
    if os.path.isabs(rel):
        return None
    return PurePosixPath(*PurePath(rel).parts).as_posix()


def read_cargo_metadata(
    target: Path, manifest: str = _MANIFEST
) -> CargoMetadata | None:
    """Run ``cargo metadata --format-version 1 --no-deps --offline`` on ``target``.

    Strictly read-only and offline: creates no files and never executes build
    scripts or ``rustc``. Returns ``None`` when ``cargo`` is missing, fails,
    times out, or resolves a workspace outside ``target``, so callers can fall
    back to manifest parsing.
    """
    cargo = shutil.which("cargo")
    if cargo is None:
        return None
    root = target.resolve()
    manifest_abs = root / manifest
    if not manifest_abs.is_file() or manifest_abs.is_symlink():
        return None
    try:
        result = subprocess.run(  # noqa: S603 # nosec B603
            [
                cargo,
                "metadata",
                "--format-version",
                "1",
                "--no-deps",
                "--offline",
                "--manifest-path",
                str(manifest_abs),
            ],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CARGO_METADATA_TIMEOUT_S,
            env=_cargo_metadata_env(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        raw = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    ws_root_str = raw.get("workspace_root")
    if not isinstance(ws_root_str, str):
        return None
    try:
        ws_root = Path(ws_root_str).resolve()
    except OSError:
        return None
    if manifest == _MANIFEST:
        if ws_root != root:
            return None
    elif ws_root != root and root not in ws_root.parents:
        return None
    raw_packages = raw.get("packages")
    if not isinstance(raw_packages, list):
        return None
    id_to_manifest: dict[str, str] = {}
    packages: list[CargoPackageMetadata] = []
    for entry in raw_packages:
        if not isinstance(entry, dict):
            continue
        pkg_name = entry.get("name")
        manifest_path_str = entry.get("manifest_path")
        if not isinstance(pkg_name, str) or not isinstance(manifest_path_str, str):
            continue
        pkg_manifest = _rel_under_root(manifest_path_str, root)
        if pkg_manifest is None:
            continue
        pkg_id = entry.get("id")
        if isinstance(pkg_id, str):
            id_to_manifest[pkg_id] = pkg_manifest
        raw_targets = entry.get("targets")
        targets: list[CargoTarget] = []
        if isinstance(raw_targets, list):
            for t in raw_targets:
                if not isinstance(t, dict):
                    continue
                t_name = t.get("name")
                t_kinds = t.get("kind")
                t_src = t.get("src_path")
                if (
                    not isinstance(t_name, str)
                    or not isinstance(t_kinds, list)
                    or not isinstance(t_src, str)
                ):
                    continue
                src_rel = _rel_under_root(t_src, root)
                if src_rel is None:
                    continue
                kinds = tuple(k for k in t_kinds if isinstance(k, str))
                t_ed = t.get("edition")
                targets.append(
                    CargoTarget(
                        name=t_name,
                        kinds=kinds,
                        src_path=src_rel,
                        edition=t_ed if isinstance(t_ed, str) else None,
                    )
                )
        pkg_ed = entry.get("edition")
        packages.append(
            CargoPackageMetadata(
                name=pkg_name,
                manifest_path=pkg_manifest,
                targets=tuple(targets),
                edition=pkg_ed if isinstance(pkg_ed, str) else None,
            )
        )
    raw_ws_members = raw.get("workspace_members")
    ws_members = frozenset(
        id_to_manifest[mid]
        for mid in (raw_ws_members if isinstance(raw_ws_members, list) else [])
        if isinstance(mid, str) and mid in id_to_manifest
    )
    return CargoMetadata(packages=tuple(packages), workspace_members=ws_members)


def read_all_cargo_metadata(
    target: Path, manifests: Sequence[str]
) -> dict[str, CargoPackageMetadata]:
    """Read Cargo metadata for the root workspace and any non-member path deps."""
    found: dict[str, CargoPackageMetadata] = {}
    wanted = set(manifests)
    root_meta = read_cargo_metadata(target, _MANIFEST)
    if root_meta is not None:
        for pkg in root_meta.packages:
            found[pkg.manifest_path] = pkg
    for manifest in manifests:
        if manifest in found or manifest == _MANIFEST:
            continue
        sub_meta = read_cargo_metadata(target, manifest)
        if sub_meta is None:
            continue
        for pkg in sub_meta.packages:
            if pkg.manifest_path in wanted:
                found.setdefault(pkg.manifest_path, pkg)
    return found


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _load(path: Path) -> Table:
    try:
        raw = read_regular_nofollow(path).decode("utf-8")
        return tomllib.loads(raw)
    except (OSError, SafetyError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValidationError(
            f"cannot read Cargo manifest {path.as_posix()}: {exc}"
        ) from exc


def _is_inherited(value: object) -> bool:
    return isinstance(value, dict) and value.get("workspace") is True


def _inherited_or_own(
    package: Table, workspace_package: Table, key: str
) -> object | None:
    value = package.get(key)
    return workspace_package.get(key) if _is_inherited(value) else value


def _within(key: str, prefix: str) -> bool:
    """Whether normalized relative path ``key`` is ``prefix`` or below it."""
    return prefix == "." or key == prefix or key.startswith(f"{prefix}{os.sep}")


def _is_excluded(key: str, workspace: Table) -> bool:
    """Cargo's rule: a literal path prefix, unless a member literal also covers it.

    Cargo does not expand globs in ``exclude`` (verified with cargo 1.100.0).
    """
    excluded = any(
        _within(key, os.path.normpath(_relative_pattern(pattern)))
        for pattern in _strings(workspace.get("exclude"))
    )
    return excluded and not any(
        _within(key, os.path.normpath(pattern))
        for pattern in _strings(workspace.get("members"))
    )


def _member_dirs(root: Path, workspace: Table) -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in _strings(workspace.get("members")):
        for directory in _expand(root, pattern):
            key = os.path.normpath(os.path.relpath(directory, root))
            if not _is_excluded(key, workspace):
                found.setdefault(key, directory)
    return list(found.values())


def _relative_pattern(pattern: str) -> str:
    if not pattern or PurePath(pattern).is_absolute():
        raise ValidationError(f"workspace member pattern must be relative: {pattern!r}")
    return pattern


def _expand(root: Path, pattern: str) -> list[Path]:
    _relative_pattern(pattern)
    if not _GLOB_CHARS & set(pattern):
        literal = root / pattern
        if not literal.is_dir():
            raise ValidationError(f"workspace member is not a directory: {pattern!r}")
        return [literal]
    # Cargo skips files a glob matches but errors on a matched directory
    # that lacks a manifest (verified with cargo 1.100.0).
    return sorted(match for match in root.glob(pattern) if match.is_dir())


def _member_manifest(root: Path, directory: Path) -> Table:
    manifest = directory / _MANIFEST
    try:
        assert_under_root(directory, root)
        assert_under_root(manifest, root)
    except SafetyError as exc:
        raise ValidationError(f"workspace member outside the root: {exc}") from exc
    return _load(manifest)


def _through_symlink(root: Path, directory: Path) -> bool:
    """Whether reaching a path dependency's manifest follows a symlink."""
    try:
        assert_under_root(directory / _MANIFEST, root)
    except SafetyError:
        return True
    return False


def _auto_bins(directory: Path, claimed: set[str]) -> list[str]:
    bin_dir = directory / "src" / "bin"
    stems: list[str] = []
    try:
        entries = sorted(os.scandir(bin_dir), key=lambda entry: entry.name)
    except OSError:
        return stems
    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_file() and entry.name.endswith(".rs"):
            if os.path.join("src", "bin", entry.name) not in claimed:
                stems.append(entry.name[: -len(".rs")])
        elif (
            entry.is_dir()
            and (Path(entry.path) / "main.rs").is_file()
            and os.path.join("src", "bin", entry.name, "main.rs") not in claimed
        ):
            stems.append(entry.name)
    return stems


def _has_main(directory: Path) -> bool:
    main = directory / "src" / "main.rs"
    return main.is_file() and not main.is_symlink()


def _claimed_bin_paths(entries: list[Table]) -> set[str]:
    """Files a [[bin]] claims by path, which are not other discovered binaries."""
    return {
        os.path.normpath(path)
        for entry in entries
        if isinstance(path := entry.get("path"), str)
    }


def _bin_entries(data: Table) -> list[Table]:
    declared = data.get("bin")
    return [e for e in (declared if isinstance(declared, list) else []) if _table(e)]


def _package_bins(
    directory: Path,
    data: Table,
    package: Table,
    name: str,
    workspace_package: Table | None = None,
) -> list[str]:
    entries = _bin_entries(data)
    bins = [
        value for entry in entries if (value := _text(entry.get("name"))) is not None
    ]
    claimed = _claimed_bin_paths(entries)
    if auto_discovery_enabled(data, "bin", workspace_package):
        if _has_main(directory) and os.path.join("src", "main.rs") not in claimed:
            bins.append(name)
        bins.extend(_auto_bins(directory, claimed))
    return bins


def auto_discovered_bins(
    directory: Path,
    data: Table,
    *,
    workspace_package: Table | None = None,
) -> list[tuple[str, str]]:
    """``(name, path)`` of each ``src/bin`` binary, with its path under ``directory``.

    No manifest spells these names: each is the file or directory stem.
    """
    if not auto_discovery_enabled(data, "bin", workspace_package):
        return []
    declared_bin_names = {
        name for sec, name in declared_target_names(data) if sec == "bin"
    }
    found: list[tuple[str, str]] = []
    for stem in _auto_bins(directory, _claimed_bin_paths(_bin_entries(data))):
        if stem in declared_bin_names:
            continue
        file = f"src/bin/{stem}.rs"
        found.append(
            (stem, file if (directory / file).is_file() else f"src/bin/{stem}")
        )
    return found


def _author(raw: object) -> tuple[str | None, str | None]:
    """Parse the first ``Name <email>`` entry; either part may be absent."""
    entries = raw if isinstance(raw, list) else []
    first = next((e for e in entries if isinstance(e, str)), None)
    if first is None or len(first) > _AUTHOR_MAX_CHARS:
        return None, None
    name, opener, rest = first.partition("<")
    email = rest.partition(">")[0] if opener else None
    return _text(name), _text(email)


def _dependency_tables(data: Table) -> list[Table]:
    tables = [_table(data.get(section)) for section in _DEPENDENCY_SECTIONS]
    for target_entry in _table(data.get("target")).values():
        tables.extend(
            _table(_table(target_entry).get(section))
            for section in _DEPENDENCY_SECTIONS
        )
    return tables


def _resolved_dependency(key: str, spec: object, workspace_deps: Table) -> str | None:
    """The registry package name an entry points at, or ``None`` when local."""
    if isinstance(spec, str):
        return key
    if not isinstance(spec, dict) or "path" in spec:
        return None
    if spec.get("workspace") is True:
        inherited = workspace_deps.get(key)
        return None if inherited is None else _resolved_dependency(key, inherited, {})
    return _text(spec.get("package")) or key


def _external_dependencies(manifests: list[Table], workspace_deps: Table) -> list[str]:
    tables = [workspace_deps]
    for data in manifests:
        tables.extend(_dependency_tables(data))
    resolved = (
        _resolved_dependency(key, spec, workspace_deps)
        for table in tables
        for key, spec in table.items()
    )
    return sorted({name for name in resolved if name is not None})


def _path_dependency_dirs(
    directory: Path, data: Table, workspace_deps: Table, root: Path
) -> list[Path]:
    """Directories of this manifest's path dependencies, lexically normalized."""
    found: list[Path] = []
    for table in _dependency_tables(data):
        for key, spec in table.items():
            base, entry = directory, _table(spec)
            if entry.get("workspace") is True:
                base, entry = root, _table(workspace_deps.get(key))
            path = entry.get("path")
            if isinstance(path, str):
                found.append(Path(os.path.normpath(base / path)))
    return found


def _workspace_manifests(
    root: Path, root_data: Table, workspace: Table, workspace_deps: Table
) -> list[tuple[Path, Table]]:
    """The root, its members, and path dependencies Cargo makes members.

    Only a ``[workspace]`` root gains members this way. A dependency outside the
    root, excluded, or without a manifest is not a member.
    """
    manifests: list[tuple[Path, Table]] = [(root, root_data)]
    seen = {"."}
    for directory in _member_dirs(root, workspace):
        key = os.path.normpath(os.path.relpath(directory, root))
        if key not in seen:
            seen.add(key)
            manifests.append((directory, _member_manifest(root, directory)))
    if "workspace" not in root_data:
        return manifests
    index = 0
    while index < len(manifests):
        directory, data = manifests[index]
        index += 1
        for dependency in _path_dependency_dirs(directory, data, workspace_deps, root):
            key = os.path.relpath(dependency, root)
            if (
                key in seen
                or key == os.pardir
                or key.startswith(f"{os.pardir}{os.sep}")
                or _is_excluded(key, workspace)
                or not os.path.lexists(dependency / _MANIFEST)
            ):
                continue
            seen.add(key)
            manifests.append((dependency, _member_manifest(root, dependency)))
    return manifests


def _declared_dependency_paths(data: Table) -> list[DeclaredPath]:
    workspace = _table(data.get("workspace"))
    tables = [*_dependency_tables(data), _table(workspace.get("dependencies"))]
    tables.extend(_table(entry) for entry in _table(data.get("patch")).values())
    tables.append(_table(data.get("replace")))
    return [
        DeclaredPath("dependency", f"dependency {key!r} path", path)
        for table in tables
        for key, spec in table.items()
        if isinstance(path := _table(spec).get("path"), str)
    ]


def declared_cargo_paths(data: Table) -> list[DeclaredPath]:
    """Every declared path in one parsed manifest, in a stable order."""
    workspace = _table(data.get("workspace"))
    found = [
        DeclaredPath("member", f"workspace {key}", item)
        for key in ("members", "default-members")
        for item in _strings(workspace.get(key))
    ]
    # Cargo matches `exclude` as literal prefixes, never as globs.
    found.extend(
        DeclaredPath("exclude", "workspace exclude", item)
        for item in _strings(workspace.get("exclude"))
    )
    found.extend(_declared_dependency_paths(data))
    if isinstance(path := _table(data.get("lib")).get("path"), str):
        found.append(DeclaredPath("target", "[lib] path", path))
    for section in _TARGET_SECTIONS:
        entries = data.get(section)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(path := _table(entry).get("path"), str):
                found.append(DeclaredPath("target", f"[[{section}]] path", path))
    package = package_table(data)
    pkg_key = _package_section_name(data)
    if isinstance(build := package.get("build"), str):
        found.append(DeclaredPath("build", f"{pkg_key}.build", build))
    if isinstance(root := package.get("workspace"), str):
        found.append(DeclaredPath("workspace", f"{pkg_key}.workspace", root))
    return found


def named_target_files(
    data: Table,
    *,
    workspace_package: Table | None = None,
) -> list[str]:
    """Files Cargo may read for each named target that declares no path."""
    ed2015 = effective_edition(data, workspace_package) == "2015"
    found: list[str] = []
    for section, name in _unpathed_targets(data):
        for shape in _TARGET_SHAPES:
            found.append(f"{_INFERRED_DIRS[section]}/{shape.format(name)}")
        if section == "bin" and ed2015:
            found.extend((f"src/{name}.rs", "src/main.rs", "src/bin/main.rs"))
    return found


def _unpathed_targets(data: Table) -> list[tuple[str, str]]:
    """``(section, name)`` of each named target that declares no ``path``."""
    found: list[tuple[str, str]] = []
    for section in _TARGET_SECTIONS:
        entries = data.get(section)
        for entry in entries if isinstance(entries, list) else []:
            table = _table(entry)
            if "path" not in table and isinstance(name := table.get("name"), str):
                found.append((section, name))
    return found


def _has_lib(directory: Path, data: Table) -> bool:
    """Whether ``data`` defines or auto-discovers a library target."""
    lib = data.get("lib")
    if isinstance(lib, dict):
        if isinstance(path := lib.get("path"), str):
            return (directory / path).is_file()
        return (directory / "src" / "lib.rs").is_file()
    package = package_table(data)
    if package.get("autolib") is False:
        return False
    return (directory / "src" / "lib.rs").is_file()


def inferred_target_paths(
    before: Table,
    after: Table,
    directory: Path,
    *,
    pkg_meta: CargoPackageMetadata | None = None,
    workspace_package: Table | None = None,
) -> list[tuple[DeclaredPath, DeclaredPath]] | None:
    """Paths Cargo infers from a target's ``name``, before and after a rewrite.

    Uses ``cargo metadata`` when available so edition-2015 fallbacks
    (``src/<name>.rs`` without a lib) and exact Cargo target inference are
    preserved; falls back to manifest/filesystem probing otherwise.
    Fixed conventional paths (``src/main.rs``, ``src/bin/main.rs``) do not
    depend on the target's name and are checked by the conventional-root check.
    ``None`` means the rewrite changes which targets declare no path.
    """
    old, new = _unpathed_targets(before), _unpathed_targets(after)
    if [section for section, _ in old] != [section for section, _ in new]:
        return None
    meta_by_key: dict[tuple[str, str], str] = {}
    if pkg_meta is not None:
        manifest_dir = posixpath.dirname(pkg_meta.manifest_path)
        for target in pkg_meta.targets:
            crate_rel = (
                posixpath.relpath(target.src_path, manifest_dir)
                if manifest_dir
                else target.src_path
            )
            for kind in target.kinds:
                if kind in _INFERRED_DIRS:
                    meta_by_key.setdefault((kind, target.name), crate_rel)
    ed2015 = effective_edition(before, workspace_package) == "2015"
    has_lib = _has_lib(directory, before) if ed2015 else True
    pairs: list[tuple[DeclaredPath, DeclaredPath]] = []
    for (section, name), (_section, new_name) in zip(old, new, strict=True):
        base = _INFERRED_DIRS[section]
        key = f"[[{section}]] {name!r} inferred path"
        if pkg_meta is not None:
            resolved = meta_by_key.get((section, name))
            if resolved is None:
                continue
            if resolved == f"{base}/{name}.rs":
                pairs.append(
                    (
                        DeclaredPath("target", key, resolved),
                        DeclaredPath("target", key, f"{base}/{new_name}.rs"),
                    )
                )
            elif resolved == f"{base}/{name}/main.rs":
                pairs.append(
                    (
                        DeclaredPath("target", key, resolved),
                        DeclaredPath("target", key, f"{base}/{new_name}/main.rs"),
                    )
                )
            elif section == "bin" and resolved == f"src/{name}.rs":
                pairs.append(
                    (
                        DeclaredPath("target", key, resolved),
                        DeclaredPath("target", key, f"src/{new_name}.rs"),
                    )
                )
            continue
        matched = False
        for shape in _TARGET_SHAPES:
            path = directory / base / shape.format(name)
            if path.is_file() and not path.is_symlink():
                pairs.append(
                    (
                        DeclaredPath("target", key, f"{base}/{shape.format(name)}"),
                        DeclaredPath("target", key, f"{base}/{shape.format(new_name)}"),
                    )
                )
                matched = True
                break
        if not matched and section == "bin" and ed2015 and not has_lib:
            legacy = directory / "src" / f"{name}.rs"
            if legacy.is_file() and not legacy.is_symlink():
                pairs.append(
                    (
                        DeclaredPath("target", key, f"src/{name}.rs"),
                        DeclaredPath("target", key, f"src/{new_name}.rs"),
                    )
                )
    return pairs


def inferred_target_candidates(
    data: Table,
) -> list[tuple[str, str, tuple[str, ...]]]:
    """``(section, name, candidate_rel_paths)`` for each pathless target.

    Cargo checks ``<dir>/<name>.rs`` and ``<dir>/<name>/main.rs`` for every
    pathless ``[[bin]]``, ``[[test]]``, ``[[example]]``, and ``[[bench]]``
    regardless of ``auto*`` flags. For ``[[bin]]`` matching ``[package].name``,
    ``src/main.rs`` is also an inferred candidate.
    """
    pkg_name = _text(package_table(data).get("name"))
    found: list[tuple[str, str, tuple[str, ...]]] = []
    for section, name in _unpathed_targets(data):
        base = _INFERRED_DIRS[section]
        paths = [f"{base}/{shape.format(name)}" for shape in _TARGET_SHAPES]
        if section == "bin" and pkg_name is not None and name == pkg_name:
            paths.insert(0, "src/main.rs")
        found.append((section, name, tuple(paths)))
    return found


def _claimed_section_paths(data: Table, section: str) -> frozenset[str]:
    """POSIX-normalized ``path`` strings declared on ``[[<section>]]`` tables."""
    entries = data.get(section)
    return frozenset(
        posixpath.normpath(path.replace("\\", "/"))
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(path := _table(entry).get("path"), str)
    )


def declared_target_names(data: Table) -> frozenset[tuple[str, str]]:
    """``(section, name)`` of every explicit target table, pathed or pathless."""
    found: set[tuple[str, str]] = set()
    for section in _TARGET_SECTIONS:
        entries = data.get(section)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(name := _table(entry).get("name"), str):
                found.add((section, name))
    return frozenset(found)


def auto_target_sections(
    data: Table,
    *,
    workspace_package: Table | None = None,
    edition_override: str | None = None,
) -> list[tuple[str, str, str, frozenset[str], str | None]]:
    """``(section, base_dir, auto_flag, claimed_posix, package_name)`` for each
    target section whose auto-discovery is enabled.

    Returns an empty list for virtual manifests (no ``[package]``/``[project]``
    table). ``claimed_posix`` holds POSIX-normalized explicit ``path`` values
    declared by ``[[<section>]]`` tables in ``data``.
    """
    package = package_table(data)
    if not package:
        return []
    pkg_name = _text(package.get("name"))
    sections: list[tuple[str, str, str, frozenset[str], str | None]] = []
    for section in _TARGET_SECTIONS:
        auto_flag = TARGET_AUTO_FLAGS[section]
        if not auto_discovery_enabled(
            data, section, workspace_package, edition_override=edition_override
        ):
            continue
        sections.append(
            (
                section,
                _INFERRED_DIRS[section],
                auto_flag,
                _claimed_section_paths(data, section),
                pkg_name,
            )
        )
    return sections


def cargo_manifest_files(target: Path) -> tuple[str, ...]:
    """Root-relative POSIX paths of the manifests a build of ``target`` reads.

    That is the workspace plus every path dependency inside the root, including
    one excluded from the workspace. An unreferenced ``Cargo.toml`` is absent.
    """
    root = target.resolve()
    root_data = _load(root / _MANIFEST)
    workspace = _table(root_data.get("workspace"))
    manifests = _workspace_manifests(
        root, root_data, workspace, _table(workspace.get("dependencies"))
    )
    seen = {os.path.normpath(os.path.relpath(path, root)) for path, _ in manifests}
    index = 0
    while index < len(manifests):
        directory, data = manifests[index]
        index += 1
        for declared in declared_cargo_paths(data):
            if declared.kind != "dependency":
                continue
            dependency = Path(os.path.normpath(directory / declared.value))
            key = os.path.relpath(dependency, root)
            if (
                key in seen
                or key == os.pardir
                or key.startswith(f"{os.pardir}{os.sep}")
                or not os.path.lexists(dependency / _MANIFEST)
            ):
                continue
            seen.add(key)
            if _through_symlink(root, dependency):
                # The press writes no file through a symlink. A directory the
                # link reaches inside the root is rewritten at its real path,
                # so its manifest is read there; one outside is left to Cargo.
                real = dependency.resolve()
                real_key = os.path.relpath(real, root)
                if real_key in seen or _through_symlink(root, real):
                    continue
                seen.add(real_key)
                dependency = real
            manifests.append((dependency, _member_manifest(root, dependency)))
    return tuple(
        Path(os.path.relpath(directory / _MANIFEST, root)).as_posix()
        for directory, _ in manifests
    )


def read_cargo_facts(target: Path) -> CargoFacts:
    """Identity facts from the root ``Cargo.toml`` and its workspace members."""
    # Only the manifest leaves are untrusted; the target path may use symlinks.
    root = target.resolve()
    root_data = _load(root / _MANIFEST)
    workspace = _table(root_data.get("workspace"))
    workspace_package = _table(workspace.get("package"))
    workspace_deps = _table(workspace.get("dependencies"))

    manifests = _workspace_manifests(root, root_data, workspace, workspace_deps)
    meta = read_cargo_metadata(root)
    meta_by_manifest = (
        {pkg.manifest_path: pkg for pkg in meta.packages} if meta is not None else {}
    )

    packages: list[str] = []
    names: set[str] = set()
    bins: set[str] = set()
    author: tuple[str | None, str | None] = (None, None)
    repository: str | None = None
    primary: str | None = None
    for directory, data in manifests:
        package = package_table(data)
        if not package:
            continue
        name = _text(package.get("name"))
        if name is None:
            raise ValidationError(f"Cargo package has no name: {directory}")
        packages.append(name)
        names.add(name)
        if directory == root:
            primary = name
        if (lib := _text(_table(data.get("lib")).get("name"))) is not None:
            names.add(lib)
        rel_manifest = Path(os.path.relpath(directory / _MANIFEST, root)).as_posix()
        pkg_meta = meta_by_manifest.get(rel_manifest)
        if pkg_meta is not None:
            bins.update(t.name for t in pkg_meta.targets if "bin" in t.kinds)
        else:
            bins.update(
                _package_bins(directory, data, package, name, workspace_package)
            )
        if author == (None, None):
            author = _author(_inherited_or_own(package, workspace_package, "authors"))
        repository = repository or _text(
            _inherited_or_own(package, workspace_package, "repository")
        )
    if author == (None, None):
        author = _author(workspace_package.get("authors"))
    repository = repository or _text(workspace_package.get("repository"))

    return CargoFacts(
        names=tuple(sorted(names | bins)),
        packages=tuple(packages),
        bins=tuple(sorted(bins)),
        primary=primary,
        author=author[0],
        email=author[1],
        repository=repository,
        external_dependencies=tuple(
            _external_dependencies([data for _, data in manifests], workspace_deps)
        ),
    )
