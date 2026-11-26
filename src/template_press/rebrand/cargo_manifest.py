"""Read the identity-bearing facts of a target's Cargo manifests.

The manifests are attacker-controlled input (they ship inside the target), so
every file is read as a regular, non-symlinked UTF-8 file and every workspace
member is checked for containment before it is read. A manifest that is
malformed, symlinked, or outside the target root raises ``ValidationError``.
Names are kept exactly as authored; hyphens are never normalized.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.safety import (
    SafetyError,
    assert_under_root,
    read_regular_nofollow,
)

_MANIFEST = "Cargo.toml"
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
_INFERRED_DIRS = {
    "bin": "src/bin",
    "test": "tests",
    "example": "examples",
    "bench": "benches",
}
_GLOB_CHARS = frozenset("*?[")
# A longer author entry is undiscoverable, never truncated into a guess.
_AUTHOR_MAX_CHARS = 1024

Table = dict[str, object]


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


def _package_bins(directory: Path, data: Table, package: Table, name: str) -> list[str]:
    entries = _bin_entries(data)
    bins = [
        value for entry in entries if (value := _text(entry.get("name"))) is not None
    ]
    claimed = _claimed_bin_paths(entries)
    if package.get("autobins") is not False:
        if _has_main(directory) and os.path.join("src", "main.rs") not in claimed:
            bins.append(name)
        bins.extend(_auto_bins(directory, claimed))
    return bins


def auto_discovered_bins(directory: Path, data: Table) -> list[tuple[str, str]]:
    """``(name, path)`` of each ``src/bin`` binary, with its path under ``directory``.

    No manifest spells these names: each is the file or directory stem.
    """
    package = _table(data.get("package"))
    if not package or package.get("autobins") is False:
        return []
    found: list[tuple[str, str]] = []
    for stem in _auto_bins(directory, _claimed_bin_paths(_bin_entries(data))):
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
    package = _table(data.get("package"))
    if isinstance(build := package.get("build"), str):
        found.append(DeclaredPath("build", "package.build", build))
    if isinstance(root := package.get("workspace"), str):
        found.append(DeclaredPath("workspace", "package.workspace", root))
    return found


def named_target_files(data: Table) -> list[str]:
    """Both files Cargo may read for each named target that declares no path."""
    return [
        f"{_INFERRED_DIRS[section]}/{shape.format(name)}"
        for section, name in _unpathed_targets(data)
        for shape in ("{}.rs", "{}/main.rs")
    ]


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


def inferred_target_paths(
    before: Table, after: Table, directory: Path
) -> list[tuple[DeclaredPath, DeclaredPath]] | None:
    """Paths Cargo infers from a target's ``name``, before and after a rewrite.

    Cargo looks for ``<dir>/<name>.rs`` or ``<dir>/<name>/main.rs``. A target
    found neither way (a ``[[bin]]`` on ``src/main.rs``) is not judged here.
    ``None`` means the rewrite changes which targets declare no path.
    """
    old, new = _unpathed_targets(before), _unpathed_targets(after)
    if [section for section, _ in old] != [section for section, _ in new]:
        return None
    pairs: list[tuple[DeclaredPath, DeclaredPath]] = []
    for (section, name), (_section, new_name) in zip(old, new, strict=True):
        base = _INFERRED_DIRS[section]
        for shape in ("{}.rs", "{}/main.rs"):
            path = directory / base / shape.format(name)
            if path.is_file() and not path.is_symlink():
                key = f"[[{section}]] {name!r} inferred path"
                pairs.append(
                    (
                        DeclaredPath("target", key, f"{base}/{shape.format(name)}"),
                        DeclaredPath("target", key, f"{base}/{shape.format(new_name)}"),
                    )
                )
                break
    return pairs


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

    packages: list[str] = []
    names: set[str] = set()
    bins: set[str] = set()
    author: tuple[str | None, str | None] = (None, None)
    repository: str | None = None
    primary: str | None = None
    for directory, data in manifests:
        package = _table(data.get("package"))
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
        bins.update(_package_bins(directory, data, package, name))
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
