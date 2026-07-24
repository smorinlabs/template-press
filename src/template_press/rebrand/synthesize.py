"""Deterministic, equality-preserving, containment-safe synthetic identity
(Task 10, Decision 6) — the synthetic TO-identity `press verify` presses the
hermetic sandbox toward.

`synthesize_dest(source)` is the only public entry point. Four properties
are load-bearing (each independently tested in test_synthesize.py):

1. **Deterministic** — a pure function of `source`, built only from
   `hashlib.sha256` (no `random`/`time`/`uuid`).
2. **Equality-preserving (D6)** — two SOURCE fields holding the SAME value
   get the SAME dest value (so an intentional equality, e.g. package_name
   == app_name, survives the press and doesn't manufacture a mismatch); two
   DISTINCT source values get DISTINCT dest values. Distinctness is
   verified explicitly against a running `used` set at construction time,
   not merely assumed from hash entropy.
3. **Valid** — every dest value passes `Identity.validate()` for its own
   field(s). A value shared by fields of DIFFERENT shapes (an equality
   class) gets a form valid for the INTERSECTION of those shapes: for a
   valid source, the only fields that can validly share a value are
   {package_name, repo_name, app_name, owner, author} (their charsets all
   permit a lowercase-letter-led alphanumeric token) or {email, author}
   (email's `local@domain.tld` shape happens to also satisfy author's
   near-unrestricted charset) — email can never coincide with an
   identifier-shaped field because `@`/`.` are outside their charsets, so
   `Identity.validate()` already rejects that combination upstream.
4. **Containment-free vs variants** — no dest value is a substring of any
   source value's separator/case/concat variant, and no such variant is a
   substring of any dest value. Every candidate carries a synthetic prefix
   whose leading letter AND hex body are both derived from
   `sha256(seed \\x00 counter)` — the counter is folded into the hash input
   on every attempt (never re-derived from a fixed literal), so a
   single-character source value (e.g. `owner="z"`) cannot collide with
   every producible candidate the way a hardcoded leading character would
   (see the `test_single_char_*` regression tests). Both retry loops
   (`_safe_prefix`, `_synth_value`) are bounded by `_MAX_ATTEMPTS` and raise
   `ValidationError` — loud, not a hang — if a pathological input ever
   exhausts the budget (e.g. an equality class colliding with a source
   value that is itself one of the mandatory structural characters of the
   email shape, like `.` or `@`).
"""

from __future__ import annotations

import hashlib

from template_press.rebrand.identity import REQUIRED_FIELDS, Identity, ValidationError

# Separator/concat forms considered when re-joining split words into a
# source variant (mirrors the separator set identity.py/matcher.py treat as
# identity boundaries: underscore, hyphen, dot, space, and glued/concat).
_JOIN_SEPARATORS: tuple[str, ...] = ("_", "-", ".", " ", "")

_PREFIX_SEED = "template-press:synthesize:prefix"
_PREFIX_HEX_LEN = 9  # + 1 hash-derived leading letter = 10 chars
_TOKEN_LEN = 24  # well under owner's 39-char cap
_EMAIL_LOCAL_HEX_LEN = 6  # + prefix
_EMAIL_DOMAIN_LEN = 10
_EMAIL_TLD_LEN = 3
# Bounded retry cap shared by both search loops: fail loud (ValidationError)
# rather than hang if a pathological input ever exhausts it. In practice a
# collision is resolved within a handful of attempts (see module docstring
# point 4); 1000 is a generous margin, not a tuned/expected value.
_MAX_ATTEMPTS = 1000


def synthesize_dest(source: Identity) -> Identity:
    """Build the deterministic synthetic TO-identity for `source`."""
    values = source.as_dict_prompted()
    display = values.pop("display_name", None)
    classes: dict[str, list[str]] = {}
    for field in REQUIRED_FIELDS:
        classes.setdefault(values[field], []).append(field)

    variant_inputs = list(values.values())
    if display is not None:
        variant_inputs.append(display)
    variants = _source_variants(variant_inputs)
    prefix = _safe_prefix(variants)

    dest_by_value: dict[str, str] = {}
    used: set[str] = set()
    for value, fields in classes.items():
        dest_by_value[value] = _synth_value(value, fields, prefix, used, variants)

    dest = Identity(
        **{field: dest_by_value[values[field]] for field in REQUIRED_FIELDS},
        display_name=(
            _synth_display(display, variants, used) if display is not None else None
        ),
    )
    dest.validate()
    return dest


# --- per-value synthesis ---------------------------------------------------


def _synth_value(
    value: str,
    fields: list[str],
    prefix: str,
    used: set[str],
    variants: frozenset[str],
) -> str:
    """One dest value for one equality class of source values.

    Bounded retry (`_MAX_ATTEMPTS`): the attempt counter is folded into the
    sha256 input every iteration, so each candidate is a genuinely new,
    still-deterministic value (never a re-derivation of the same colliding
    candidate). Accepted only once distinct from every dest value already
    minted (explicit distinctness check, property 2) and containment-free
    against the source's variant set (property 4). Raises `ValidationError`
    — never loops forever — if the budget is exhausted.
    """
    is_email = "email" in fields
    for counter in range(_MAX_ATTEMPTS):
        digest = hashlib.sha256(f"{value}\x00{counter}".encode()).hexdigest()
        candidate = (
            _email_form(prefix, digest) if is_email else _token_form(prefix, digest)
        )
        if candidate not in used and not _collides(candidate, variants):
            used.add(candidate)
            return candidate
    raise ValidationError(
        f"synthesize: could not derive a distinct, containment-free value "
        f"for field(s) {', '.join(fields)} within {_MAX_ATTEMPTS} attempts"
    )


def _token_form(prefix: str, digest: str) -> str:
    """Lowercase-letter-led alphanumeric token: valid simultaneously for
    package_name, repo_name, app_name, owner, and author (property 3)."""
    return (prefix + digest)[:_TOKEN_LEN]


def _email_form(prefix: str, digest: str) -> str:
    """`local@domain.tld` shape: valid for email, and (being an
    unrestricted-charset string) also valid for author (property 3)."""
    local = (prefix + digest)[: len(prefix) + _EMAIL_LOCAL_HEX_LEN]
    domain_start = _EMAIL_LOCAL_HEX_LEN
    domain = digest[domain_start : domain_start + _EMAIL_DOMAIN_LEN]
    tld_start = domain_start + _EMAIL_DOMAIN_LEN
    tld = digest[tld_start : tld_start + _EMAIL_TLD_LEN]
    return f"{local}@{domain}.{tld}"


def _synth_display(value: str, variants: frozenset[str], used: set[str]) -> str:
    """Deterministic two-word Title-Case synthetic display name.

    Both words are hash-derived from distinct digest regions using
    _word_letters to ensure they are alphabetic (not raw hex), making
    the Title-Case property structural. The candidate is rejected if its
    spaced OR glued (pascal ≈ camel under the case-insensitive `_collides`)
    form collides with any source variant, so the display rewrite pass and
    the paranoid scanner can never confuse synthetic output with surviving
    source identity.
    """
    for counter in range(_MAX_ATTEMPTS):
        digest = hashlib.sha256(f"display\x00{value}\x00{counter}".encode()).digest()
        w1 = _word_letters(digest, 0, 6)
        w2 = _word_letters(digest, 6, 6)
        candidate = f"{w1.capitalize()} {w2.capitalize()}"
        glued = w1.capitalize() + w2.capitalize()
        if (
            candidate not in used
            and not _collides(candidate, variants)
            and not _collides(glued, variants)
        ):
            used.add(candidate)
            return candidate
    raise ValidationError(
        f"synthesize: could not derive a containment-free display name within "
        f"{_MAX_ATTEMPTS} attempts"
    )


# --- containment-free prefix -----------------------------------------------


def _safe_prefix(variants: frozenset[str]) -> str:
    """A synthetic prefix verified (not merely assumed) to be
    containment-free against the ACTUAL source's variant set.

    Both the leading letter and the hex body come from
    `sha256(_PREFIX_SEED \\x00 counter)`. The counter guarantees a
    genuinely different candidate every attempt; the letter is chosen FROM
    THE HASH rather than a hardcoded literal, because a fixed leading
    character is a universal collision floor for any source value that IS
    that one character — e.g. a hardcoded `"z"` prefix collides with
    EVERY candidate whenever a source field's whole value is `"z"`, no
    matter how the rest of the candidate varies (the bug this function was
    rewritten to fix). Bounded by `_MAX_ATTEMPTS`; raises `ValidationError`
    rather than looping forever if a pathological input exhausts it.
    """
    for counter in range(_MAX_ATTEMPTS):
        digest = hashlib.sha256(f"{_PREFIX_SEED}\x00{counter}".encode()).digest()
        candidate = _leading_letter(digest) + digest.hex()[:_PREFIX_HEX_LEN]
        if not _collides(candidate, variants):
            return candidate
    raise ValidationError(
        f"synthesize: could not derive a containment-free prefix within "
        f"{_MAX_ATTEMPTS} attempts"
    )


def _leading_letter(digest: bytes) -> str:
    """Map a hash byte to a lowercase letter (a-z).

    The identifier-shaped fields (package_name/repo_name/app_name/owner)
    all require a letter-led value, but the letter must be HASH-derived —
    see `_safe_prefix`'s docstring for why a fixed constant here is unsafe.
    """
    return chr(ord("a") + digest[0] % 26)


def _word_letters(digest: bytes, start: int, count: int) -> str:
    """Map `count` digest bytes to lowercase letters (a-z), one per byte.

    Letters-only words keep the synthetic display name prose-shaped and
    make the Title-Case property structural — a raw-hex suffix could be
    all digits, and digits are uncased (str.islower() would be False).
    """
    return "".join(chr(ord("a") + digest[start + i] % 26) for i in range(count))


def _collides(candidate: str, variants: frozenset[str]) -> bool:
    """True if `candidate` is a substring of some source variant, or some
    source variant is a substring of `candidate` (checked case-insensitive,
    matching the paranoid scanner's IGNORECASE posture)."""
    lowered = candidate.lower()
    for variant in variants:
        if not variant:
            continue
        v = variant.lower()
        if v in lowered or lowered in v:
            return True
    return False


# --- source variant generation ---------------------------------------------


def _words(value: str) -> list[str]:
    """Split `value` into lowercase word tokens on separators (`_-. `) and
    lower->UPPER case transitions — the same boundary shapes the paranoid
    verifier matcher treats as identity boundaries, so the variant set built
    from these words is a superset of what a real leak-scan would flag."""
    words: list[str] = []
    current: list[str] = []
    for ch in value:
        if ch in "_-. ":
            if current:
                words.append("".join(current))
                current = []
            continue
        if current and current[-1].islower() and ch.isupper():
            words.append("".join(current))
            current = []
        current.append(ch)
    if current:
        words.append("".join(current))
    return [w.lower() for w in words if w]


def _variants(value: str) -> set[str]:
    """Separator/case/concat variant forms of one source value."""
    words = _words(value)
    forms = {value, value.lower(), value.upper()}
    if words:
        for sep in _JOIN_SEPARATORS:
            forms.add(sep.join(words))
            forms.add(sep.join(w.upper() for w in words))
            forms.add(sep.join(w.capitalize() for w in words))
        forms.add(words[0] + "".join(w.capitalize() for w in words[1:]))  # camelCase
        forms.add("".join(w.capitalize() for w in words))  # PascalCase
    return {f for f in forms if f}


def _source_variants(values: list[str]) -> frozenset[str]:
    out: set[str] = set()
    for value in values:
        out.update(_variants(value))
    return frozenset(out)
