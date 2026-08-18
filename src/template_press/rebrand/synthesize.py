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
   not merely assumed from hash entropy. This guarantee covers every
   rewrite-row slot `_identity_rows` can emit — the 6 REQUIRED_FIELDS,
   `app_name_upper` (= `app_name.upper()`), and the three
   `display_name_{spaced,pascal,camel}` forms (issue #46) — not just the
   REQUIRED_FIELDS. `_assert_equality_signature` is the two-way postcondition
   that makes this a checked property rather than an assumption: for every
   pair of slots, source-equality and dest-equality must coincide in BOTH
   directions (a lost equality is exactly what trips `pipeline.py`'s
   ambiguity guard; a NEW dest-only equality among source-distinct slots is
   just as wrong, though nothing downstream currently detects it).

   A clean `press verify` proves the target can survive the ONE coherent
   synthetic press this module generates. It does not and cannot certify an
   operator's future, unseen destination — that's not a gap in the pipeline
   guard (which independently validates every REAL press's actual
   destination and is untouched by this module), just an honest statement
   of what a hermetic self-test can prove.
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
import itertools
from collections.abc import Callable, Iterator

from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    REQUIRED_FIELDS,
    VALIDATORS,
    Identity,
    ValidationError,
    display_forms,
)

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
    """Build the deterministic synthetic TO-identity for `source`.

    Two paths, selected by whether any REQUIRED_FIELDS/app_name_upper/
    display-form slot coincidentally shares a value with another such slot
    (an "entangled" source, #46): the ORIGINAL, unchanged algorithm for the
    overwhelmingly common non-entangled case (`_synthesize_plain` — verified
    byte-identical to the pre-#46 implementation), and a signature-matching
    solver (`_synthesize_entangled`) only when entanglement is actually
    present. Both paths converge on the same two-way postcondition.
    """
    values = source.as_dict_prompted()
    display = values.pop("display_name", None)

    variant_inputs = list(values.values())
    if display is not None:
        variant_inputs.append(display)
    variants = _source_variants(variant_inputs)
    prefix = _safe_prefix(variants)

    slot_values = _slot_values(source)
    classes = _slot_classes(slot_values)
    if any(_is_entangled(slots) for slots in classes.values()):
        dest = _synthesize_entangled(values, display, classes, prefix, variants)
    else:
        dest = _synthesize_plain(values, display, prefix, variants)

    dest.validate()
    _assert_equality_signature(source, dest)
    return dest


def _synthesize_plain(
    values: dict[str, str],
    display: str | None,
    prefix: str,
    variants: frozenset[str],
) -> Identity:
    """The original (pre-#46) algorithm, unchanged: equality classes over
    REQUIRED_FIELDS only, display_name synthesized independently. Kept
    byte-identical so every non-entangled source (the common case) produces
    exactly what it always has."""
    classes: dict[str, list[str]] = {}
    for field in REQUIRED_FIELDS:
        classes.setdefault(values[field], []).append(field)

    dest_by_value: dict[str, str] = {}
    used: set[str] = set()
    for value, fields in classes.items():
        dest_by_value[value] = _synth_value(value, fields, prefix, used, variants)

    return Identity(
        **{field: dest_by_value[values[field]] for field in REQUIRED_FIELDS},
        display_name=(
            _synth_display(display, variants, used) if display is not None else None
        ),
    )


# --- #46: equality-signature preservation across derived slots -------------
#
# `_synthesize_plain`'s equality classes cover REQUIRED_FIELDS only.
# `_identity_rows` (substitutions.py) also emits rewrite rows for two
# DERIVED slots: `app_name_upper` (= app_name.upper()) and the three
# `display_name_{spaced,pascal,camel}` forms (= display_forms(display_name)).
# When a source coincidentally has one of THOSE slots sharing a value with
# another slot, the plain algorithm — which synthesizes app_name and
# display_name independently — has no way to keep them aligned, even though
# nothing forces it to misalign them. This section extends the ORIGINAL
# distinctness/containment machinery (`_synth_value`, `_collides`,
# `_source_variants`, `_safe_prefix` — all unchanged) to also solve the
# entangled classes, without ever touching the non-entangled path above.


def _slot_values(identity: Identity) -> dict[str, str]:
    """Every rewrite-row slot `_identity_rows` can emit, by name: the 6
    REQUIRED_FIELDS, `app_name_upper`, and (when present) the three
    display forms — in that insertion order."""
    values = {field: getattr(identity, field) for field in REQUIRED_FIELDS}
    values["app_name_upper"] = identity.app_name_upper
    if identity.display_name is not None:
        forms = display_forms(identity.display_name)
        for form in DISPLAY_FORM_NAMES:
            values[f"display_{form}"] = forms[form]
    return values


def _slot_classes(slot_values: dict[str, str]) -> dict[str, list[str]]:
    """Partition ALL slots (not just REQUIRED_FIELDS) by exact value
    equality — the equality graph #46 extends D6 across."""
    classes: dict[str, list[str]] = {}
    for slot, value in slot_values.items():
        classes.setdefault(value, []).append(slot)
    return classes


def _is_entangled(slots: list[str]) -> bool:
    """True when a class mixes a REQUIRED_FIELD with a derived slot (or two
    derived slots) — i.e. is NOT solvable by `_synthesize_plain`'s
    REQUIRED_FIELDS-only classing. Two REQUIRED_FIELDS sharing a value alone
    is ordinary D6, already handled by the unchanged plain path."""
    derived = [s for s in slots if s == "app_name_upper" or s.startswith("display_")]
    return bool(derived) and len(slots) > 1


def _assert_equality_signature(source: Identity, dest: Identity) -> None:
    """Two-way equality-signature postcondition: for EVERY pair of emitted
    rewrite slots, source-equality and dest-equality must coincide.

    Covers all three display forms regardless of `[rules] display_forms`
    (synthesize never sees rules — solving for the superset is deliberately
    stricter than any enabled subset). Catches both directions: a LOST
    source equality (exactly what trips `pipeline.py`'s ambiguity guard) and
    a NEW dest-only equality among source-distinct slots (constructible with
    a naive fix around non-round-tripping case mappings, e.g. "ß"/"ǅ" —
    `_synthesize_entangled`'s solver is designed to never produce one, so
    this is the unreachable backstop, not the primary correctness mechanism).
    """
    src, dst = _slot_values(source), _slot_values(dest)
    for left, right in itertools.combinations(src, 2):
        if (src[left] == src[right]) != (dst[left] == dst[right]):
            raise ValidationError(
                f"synthesize: equality signature broken for ({left}, {right}): "
                f"source {'equal' if src[left] == src[right] else 'distinct'}, "
                f"dest {'equal' if dst[left] == dst[right] else 'distinct'}"
            )


def _upper_tie_check(
    upper_slots: list[str], used: set[str], variants: frozenset[str]
) -> Callable[[str], bool]:
    """Acceptance predicate folded into `_synth_value` for app_name's class,
    when app_name_upper's class is ALSO entangled (with owner and/or
    author): a candidate is only acceptable if its UPPERCASE form also
    passes every tied REQUIRED_FIELD's validator and is itself distinct and
    containment-free — checked per-candidate inside the bounded retry, never
    as a post-hoc raise."""

    def check(candidate: str) -> bool:
        upper = candidate.upper()
        if upper in used or _collides(upper, variants):
            return False
        for slot in upper_slots:
            if slot in REQUIRED_FIELDS:
                try:
                    VALIDATORS[slot](upper)
                except ValidationError:
                    return False
        return True

    return check


def _synthesize_entangled(
    values: dict[str, str],
    display: str | None,
    classes: dict[str, list[str]],
    prefix: str,
    variants: frozenset[str],
) -> Identity:
    """Solve every entangled class together: display-driven backward
    propagation first (display -> app_name_upper -> app_name, when tied),
    then mint every remaining REQUIRED_FIELDS class exactly as
    `_synthesize_plain` does — with one addition: app_name's class carries
    an extra acceptance check when app_name_upper's class is ALSO entangled,
    so the two halves of the coupling are never solved out of order."""
    class_of = {slot: value for value, slots in classes.items() for slot in slots}
    dest_class_value: dict[str, str] = {}
    used: set[str] = set()
    upper_value = class_of["app_name_upper"]
    app_value = class_of["app_name"]

    def _ensure_upper_derived() -> None:
        # Forward-derive app_name_upper's class value the moment app_name's
        # is resolved (by ANY means — display propagation or minting) —
        # called immediately after each, before any LATER field whose
        # source value literally equals `upper_value` (e.g. owner="PRESS"
        # when app_name="press") reaches its own turn and would otherwise
        # mint an unrelated token for what is really the same class.
        if app_value not in dest_class_value or upper_value in dest_class_value:
            return
        derived_upper = dest_class_value[app_value].upper()
        dest_class_value[upper_value] = derived_upper
        used.add(derived_upper)

    dest_display: str | None = None
    if display is not None:
        dest_display, proposal = _synth_display_matched(
            display, classes, class_of, used, variants
        )
        dest_class_value.update(proposal)
        used.update(proposal.values())
        # `proposal` covers only the ENTANGLED display forms (#46 review,
        # Copilot). A form whose own class is a singleton — e.g. `spaced`/
        # `pascal` when only `camel` ties into another field, reachable for
        # any multi-word, all-distinct-signature display — never lands in
        # `proposal`, so its value must still be reserved here or a later
        # REQUIRED_FIELDS mint could accidentally choose it, introducing a
        # dest-only equality with no source basis (exactly what `_assert_
        # equality_signature` exists to catch, but reserving is cheaper and
        # keeps every accepted value in `used`, not just the tied ones).
        used.update(display_forms(dest_display).values())
        _ensure_upper_derived()

    for field in REQUIRED_FIELDS:
        value = values[field]
        if value in dest_class_value:
            continue
        fields = [f for f in REQUIRED_FIELDS if values[f] == value]
        check = None
        if value == app_value and _is_entangled(classes[upper_value]):
            check = _upper_tie_check(classes[upper_value], used, variants)
        dest_class_value[value] = _synth_value(
            value, fields, prefix, used, variants, extra_check=check
        )
        _ensure_upper_derived()

    app_dest = dest_class_value[app_value]
    if dest_class_value[upper_value] != app_dest.upper():
        raise ValidationError(
            "synthesize: internal inconsistency between app_name_upper's "
            "resolved class value and app_name's derived uppercase form"
        )

    return Identity(
        **{f: dest_class_value[values[f]] for f in REQUIRED_FIELDS},
        display_name=dest_display,
    )


# --- #46: signature-matching display-name search ---------------------------
#
# `display_forms` derives spaced/pascal/camel from ONE string, so unlike a
# REQUIRED_FIELDS class (mint a token, assign it verbatim to every member),
# an entangled display form is a CONSTRAINT on the single free variable
# `display_name`: find a candidate whose relevant derived forms equal
# already-committed class values, is valid, distinct, and containment-free
# — verified per-candidate (`_check_display_candidate`), never assumed.
# Two candidate families, tried in order: `_masked_candidates` (structure-
# preserving, bijective — the common case) then `_fallback_candidates`
# (fresh ASCII construction, for sources whose mask family is degenerate:
# pure punctuation, uncased scripts).


def _source_signature(display: str) -> tuple[bool, bool, bool]:
    """(spaced==pascal, spaced==camel, pascal==camel) for one display value.

    Determined entirely by word count and the first word's leading-
    character case class: single-word display_names split into "all three
    equal" (a digit/uncased/punctuation-leading char — case-invariant),
    "spaced==pascal only" (an already-uppercase-leading char), or
    "spaced==camel only" (an ordinary lowercase-leading letter — pascal
    capitalizes it, camel re-lowers pascal's own leading char back).
    Multi-word display_names always have spaced distinct from both derived
    forms (pascal/camel drop the whitespace `spaced` retains), and
    pascal==camel there iff the FIRST word's leading character is
    case-invariant (camel only ever re-cases pascal's very first character,
    never a later word's). Verified against real `display_forms` output for
    every reachable case, including non-round-tripping Unicode (ß, ǅ) whose
    single-word signature does not fit the three-way split above — those
    fall through to "all distinct", which is correct: `_masked_candidates`
    preserves such characters verbatim rather than trying to re-derive their
    signature, so this function is never asked to construct one.
    """
    forms = display_forms(display)
    return (
        forms["spaced"] == forms["pascal"],
        forms["spaced"] == forms["camel"],
        forms["pascal"] == forms["camel"],
    )


def _maskable_alphabet(ch: str) -> tuple[str, ...] | None:
    """The alphabet a mask position may substitute `ch` with, or None if
    `ch` must be preserved verbatim.

    A character is maskable only when its upper/lower mapping is a single,
    round-tripping character — this is what makes tier 1's preservation of
    everything else (whitespace, punctuation, "ß", "ǅ", uncased scripts)
    safe: a candidate that keeps a non-round-tripping character in place
    reproduces the SOURCE's own (possibly unusual) equality signature
    exactly, rather than risking a mask-introduced one `_check_display_
    candidate`'s signature check would then have to reject.
    """
    if ch.isdigit():
        return tuple("0123456789")
    if (
        ch.isalpha()
        and ch.islower()
        and len(ch.upper()) == 1
        and ch.upper().lower() == ch
    ):
        return tuple("abcdefghijklmnopqrstuvwxyz")
    if (
        ch.isalpha()
        and ch.isupper()
        and len(ch.lower()) == 1
        and ch.lower().upper() == ch
    ):
        return tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return None


def _mask_positions(display: str) -> list[tuple[int, tuple[str, ...]]]:
    return [
        (i, alphabet)
        for i, ch in enumerate(display)
        if (alphabet := _maskable_alphabet(ch)) is not None
    ]


def _masked_candidates(display: str) -> Iterator[str]:
    """Structure-preserving candidates for `display`, enumerated as a true
    bijection over the maskable-position family — not a with-replacement
    hash draw. When the family is small enough to fit within
    `_MAX_ATTEMPTS`, every member is visited exactly once (provably
    exhaustive, closing the "search can falsely report exhaustion" gap); when
    larger, the first `_MAX_ATTEMPTS` counters still decode to that many
    pairwise-DISTINCT candidates, strictly stronger than sampling with
    replacement. Yields nothing when `display` has no maskable position at
    all (pure punctuation/whitespace/uncased-script) — `_synth_display_
    matched` falls through to `_fallback_candidates` in that case.
    """
    positions = _mask_positions(display)
    if not positions:
        return
    sizes = [len(alphabet) for _, alphabet in positions]
    family_size = 1
    for size in sizes:
        family_size *= size
    offsets = [
        hashlib.sha256(
            f"template-press:synthesize:mask\x00{display}\x00{index}".encode()
        ).digest()[0]
        for index, _ in positions
    ]
    chars = list(display)
    for counter in range(min(family_size, _MAX_ATTEMPTS)):
        remainder = counter
        for (pos, alphabet), offset, size in zip(
            positions, offsets, sizes, strict=True
        ):
            digit = remainder % size
            remainder //= size
            chars[pos] = alphabet[(digit + offset) % size]
        yield "".join(chars)


def _fallback_candidates(display: str) -> Iterator[str]:
    """Fresh ASCII candidates reproducing `display`'s own signature (via
    `_source_signature`), for sources `_masked_candidates` cannot vary at
    all — pure punctuation or an uncased script, where every character is
    unmaskable. Deterministic (hash-derived), grows word length every 64
    attempts so it cannot exhaust against a merely-crowded `used`/variants
    set, and — like `_masked_candidates` — only affects how quickly a valid
    candidate is found; `_check_display_candidate` is what makes any
    accepted candidate correct.
    """
    sp_pa, sp_ca, pa_ca = _source_signature(display)
    single_word = sp_pa or sp_ca
    for counter in itertools.count():
        length = max(4, 4 + counter // 64)
        seed = f"template-press:synthesize:mask-fallback\x00{display}\x00{counter}"
        digest = hashlib.sha256(seed.encode()).digest()
        letters = "".join(
            chr(ord("a") + digest[i % len(digest)] % 26) for i in range(length)
        )
        if single_word:
            if sp_pa and pa_ca:  # all three forms equal: digit-led
                leading = str(digest[0] % 10)
            elif sp_pa:  # spaced == pascal only: already-uppercase-led
                leading = letters[0].upper()
            else:  # spaced == camel only: ordinary lowercase-led
                leading = letters[0]
            yield leading + letters[1:]
        else:
            split = max(2, length // 2)
            if pa_ca:  # pascal == camel: first word's leading char digit-led
                first = str(digest[0] % 10) + letters[1:split]
            else:  # all distinct: an ordinary Title-Case leading word
                first = letters[:split].capitalize()
            second = letters[split:].capitalize() or letters[:1].capitalize()
            yield f"{first} {second}"


def _entangled_display_classes(
    display: str, classes: dict[str, list[str]]
) -> dict[str, str]:
    """{form_name: class_value} for every display form whose source value
    is shared with at least one other slot."""
    src_forms = display_forms(display)
    return {
        form: src_forms[form]
        for form in DISPLAY_FORM_NAMES
        if _is_entangled(classes.get(src_forms[form], [form]))
    }


def _check_display_candidate(
    candidate: str,
    entangled_forms: dict[str, str],
    classes: dict[str, list[str]],
    class_of: dict[str, str],
    used: set[str],
    variants: frozenset[str],
) -> dict[str, str] | None:
    """The single source of truth for correctness: `candidate` is accepted
    only if EVERY constraint holds simultaneously. Returns
    {class_value: dest_value} to merge into the caller's assignment on
    success, or None to reject (the candidate families above only affect how
    quickly an accepted candidate is found, never whether an accepted one is
    actually correct).
    """
    cand_forms = display_forms(candidate)

    # 1. Realized signature must match the source's, for every pair of
    #    ENTANGLED forms — a candidate that merges or splits an entangled
    #    pair differently from the source cannot represent the same classes.
    for a, b in itertools.combinations(entangled_forms, 2):
        if (entangled_forms[a] == entangled_forms[b]) != (
            cand_forms[a] == cand_forms[b]
        ):
            return None

    # 2. One dest value per entangled class, cross-checked for consistency
    #    (two forms tied to the SAME class must propose the same value).
    proposal: dict[str, str] = {}
    for form, class_value in entangled_forms.items():
        value = cand_forms[form]
        if proposal.setdefault(class_value, value) != value:
            return None

    # 3. Backward propagation: display -> app_name_upper -> app_name.
    app_value = class_of["app_name"]
    upper_value = class_of["app_name_upper"]
    if upper_value in proposal:
        upper_dest = proposal[upper_value]
        app_dest = upper_dest.lower()
        if app_dest.upper() != upper_dest:
            return None  # non-round-tripping candidate; try the next one
        if proposal.setdefault(app_value, app_dest) != app_dest:
            return None

    # 4. Every REQUIRED_FIELD tied into a proposed class must validate it.
    for class_value, dest_value in proposal.items():
        for slot in classes[class_value]:
            if slot in REQUIRED_FIELDS:
                try:
                    VALIDATORS[slot](dest_value)
                except ValidationError:
                    return None
    try:
        VALIDATORS["display_name"](candidate)
    except ValidationError:
        return None

    # 5. Distinctness: every DIFFERENT source-side entangled class must get
    #    a DIFFERENT dest value — checked over `proposal`'s own values
    #    (already deduplicated by class_value, its dict key), plus the
    #    forward-derived app_name_upper value when it's a fresh, unrelated
    #    class. A value that naturally repeats because two FORMS of this
    #    same candidate coincide (e.g. spaced==pascal) is not a violation —
    #    step 2 already coalesced that onto one class_value via setdefault.
    distinct_required = list(proposal.values())
    if app_value in proposal and upper_value not in proposal:
        distinct_required.append(proposal[app_value].upper())
    if len(set(distinct_required)) != len(distinct_required):
        return None

    # Containment-freedom applies to every value a real press would emit —
    # all three display forms (entangled or not) plus every proposed class
    # value — each checked once, and against `used` so this candidate never
    # reuses a value some other class already committed to.
    for value in set(cand_forms.values()) | set(distinct_required):
        if value in used or _collides(value, variants):
            return None

    return proposal


def _synth_display_matched(
    display: str,
    classes: dict[str, list[str]],
    class_of: dict[str, str],
    used: set[str],
    variants: frozenset[str],
) -> tuple[str, dict[str, str]]:
    entangled_forms = _entangled_display_classes(display, classes)
    candidates = itertools.chain(
        itertools.islice(_masked_candidates(display), _MAX_ATTEMPTS),
        itertools.islice(_fallback_candidates(display), _MAX_ATTEMPTS),
    )
    for candidate in candidates:
        proposal = _check_display_candidate(
            candidate, entangled_forms, classes, class_of, used, variants
        )
        if proposal is not None:
            return candidate, proposal
    raise ValidationError(
        f"synthesize: could not derive a signature-matching destination "
        f"display name for {display!r} within the attempt budget"
    )


# --- per-value synthesis ---------------------------------------------------


def _synth_value(
    value: str,
    fields: list[str],
    prefix: str,
    used: set[str],
    variants: frozenset[str],
    extra_check: Callable[[str], bool] | None = None,
) -> str:
    """One dest value for one equality class of source values.

    Bounded retry (`_MAX_ATTEMPTS`): the attempt counter is folded into the
    sha256 input every iteration, so each candidate is a genuinely new,
    still-deterministic value (never a re-derivation of the same colliding
    candidate). Accepted only once distinct from every dest value already
    minted (explicit distinctness check, property 2) and containment-free
    against the source's variant set (property 4). Raises `ValidationError`
    — never loops forever — if the budget is exhausted.

    `extra_check` (#46, optional — every existing caller omits it, so this
    is purely additive): a further per-candidate predicate, folded into the
    SAME bounded retry rather than checked after the fact. Used only when
    app_name's class must also keep its uppercase form valid for a
    separately-entangled `app_name_upper` class (`_upper_tie_check`).
    """
    is_email = "email" in fields
    for counter in range(_MAX_ATTEMPTS):
        digest = hashlib.sha256(f"{value}\x00{counter}".encode()).hexdigest()
        candidate = (
            _email_form(prefix, digest) if is_email else _token_form(prefix, digest)
        )
        if candidate in used or _collides(candidate, variants):
            continue
        if extra_check is not None and not extra_check(candidate):
            continue
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
