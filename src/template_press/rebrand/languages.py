"""Target-language names a target may declare in ``[rules] languages``."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.safety import SafetyError, read_regular_nofollow

KNOWN_LANGUAGES: tuple[str, ...] = ("python", "node", "rust")

# Languages this press version can rebrand; the rest are reserved names.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"python"})

# Root manifest that identifies each language, in ``KNOWN_LANGUAGES`` order.
_MANIFESTS: dict[str, str] = {
    "python": "pyproject.toml",
    "node": "package.json",
    "rust": "Cargo.toml",
}


@dataclass(frozen=True)
class DetectedLanguage:
    """A language whose root manifest declares a package identity."""

    language: str
    manifest: str


@dataclass(frozen=True)
class LanguageDecision:
    """Languages to check, and detected languages deliberately ignored."""

    checked: tuple[str, ...]
    ignored: tuple[DetectedLanguage, ...]


def _declares_identity(language: str, manifest: str, data: Any) -> bool:
    """Return whether parsed manifest ``data`` declares a package identity."""

    if language == "node":
        if not isinstance(data, dict):
            raise ValidationError(f"{manifest}: top level must be a JSON object")
        if "name" not in data:
            return False
        name = data["name"]
        if not isinstance(name, str) or not name:
            raise ValidationError(f"{manifest}: 'name' must be a non-empty string")
        return True
    keys = ("project",) if language == "python" else ("package", "workspace")
    found = False
    for key in keys:
        if key in data:
            if not isinstance(data[key], dict):
                raise ValidationError(f"{manifest}: [{key}] must be a table")
            found = True
    return found


def _detect_one(target: Path, language: str, manifest: str) -> bool:
    try:
        raw = read_regular_nofollow(target / manifest)
    except FileNotFoundError:
        return False
    except (OSError, SafetyError) as exc:
        raise ValidationError(f"cannot read {manifest}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
        if language == "node":
            data: Any = json.loads(text)
        else:
            data = tomllib.loads(text)
    except (
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise ValidationError(f"cannot parse {manifest}: {exc}") from exc
    return _declares_identity(language, manifest, data)


def detect_languages(target: Path) -> tuple[DetectedLanguage, ...]:
    """Detect languages from root manifests, ordered as ``KNOWN_LANGUAGES``."""

    return tuple(
        DetectedLanguage(language, _MANIFESTS[language])
        for language in KNOWN_LANGUAGES
        if _detect_one(target, language, _MANIFESTS[language])
    )


def _undeclared_refusal(detected: tuple[DetectedLanguage, ...]) -> ValidationError:
    manifests = ", ".join(d.manifest for d in detected)
    supported = [d.language for d in detected if d.language in SUPPORTED_LANGUAGES]
    message = (
        f"target has several language manifests ({manifests}) and "
        "[rules] languages is not declared"
    )
    if supported:
        listed = ", ".join(f'"{language}"' for language in supported)
        message += f"; add this to press/press-rules.toml under [rules]: languages = [{listed}]"
    else:
        message += "; this press version supports only python"
    return ValidationError(message)


def check_target_languages(
    target: Path,
    declared: tuple[str, ...] | None,
    removed_files: Iterable[str],
) -> LanguageDecision:
    """Resolve detected languages against the declared ``[rules] languages``."""

    detected = detect_languages(target)
    if declared is None:
        if len(detected) > 1:
            raise _undeclared_refusal(detected)
        return LanguageDecision(tuple(d.language for d in detected), ())
    by_language = {d.language: d for d in detected}
    removed = {r.rstrip(" .").casefold() for r in removed_files}
    for language in declared:
        found = by_language.get(language)
        manifest = _MANIFESTS[language]
        if found is None:
            raise ValidationError(
                f"[rules] languages declares {language} but the target has no "
                f"{manifest} that declares a package identity"
            )
        if manifest.casefold() in removed:
            raise ValidationError(
                f"[rules] languages declares {language} but {manifest} is "
                "listed in remove_files"
            )
    ignored = tuple(d for d in detected if d.language not in declared)
    return LanguageDecision(declared, ignored)


def render_ignored_languages(decision: LanguageDecision) -> list[str]:
    """Return one line per detected language that is not being checked."""

    return [
        f"ignored {d.language} ({d.manifest}): not declared in [rules] languages"
        for d in decision.ignored
    ]
