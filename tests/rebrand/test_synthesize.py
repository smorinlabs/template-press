"""`synthesize_dest` — deterministic, equality-preserving, containment-safe
synthetic TO-identity (Task 10, Decision 6).

Fixture identity mirrors conftest.SOURCE (package_name="demo_widget",
repo_name="demo-widget", app_name="press", author="Demo Author",
email="demo@example.com", owner="demolabs" — all six values pairwise
distinct in the base fixture, which is what the all-distinct test needs).

The variant builder below is INDEPENDENT of any variant-generation
synthesize.py might use internally — it is a black-box "reasonable
superset" of the separator/case/concat forms `matcher.identity_pattern`
and `identity.token_pattern` treat as identity-boundary matches, so the
containment-freedom test exercises the property against the same shapes a
real leak-scan would flag, not against the implementation's own idea of a
variant.
"""

from __future__ import annotations

import re
import signal
from contextlib import contextmanager
from dataclasses import replace
from itertools import islice

import pytest

from template_press.rebrand.identity import (
    VALIDATORS,
    Identity,
    ValidationError,
    display_forms,
)
from template_press.rebrand.inventory import SurfaceSnapshot
from template_press.rebrand.rules import DEFAULT_RULES
from template_press.rebrand.substitutions import compile_substitution_table
from template_press.rebrand.synthesize import (
    _assert_equality_signature,
    _fallback_candidates,
    _is_entangled,
    _mask_positions,
    _masked_candidates,
    _slot_values,
    _source_signature,
    synthesize_dest,
)

from .conftest import SOURCE


def _identity(**kwargs: str) -> Identity:
    """Build an identity with sensible defaults matching the brief's spec."""
    defaults = {
        "package_name": "py_launch_blueprint",
        "repo_name": "py-launch-blueprint",
        "app_name": "plbp",
        "author": "Steve Morin",
        "email": "steve.morin@gmail.com",
        "owner": "smorinlabs",
    }
    defaults.update(kwargs)
    return Identity(**defaults)


_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SEPARATORS = ("_", "-", ".", " ", "")


@contextmanager
def _bounded(seconds: int = 5):
    """Fail the test (not hang the suite) if the wrapped block doesn't
    return within `seconds` — belt-and-suspenders on top of synthesize.py's
    own `_MAX_ATTEMPTS` bound, using the same SIGALRM technique the
    adversarial review used to reproduce the original 100%-reproducible
    hang in `_safe_prefix`."""

    def _on_alarm(signum, frame):
        raise TimeoutError(f"did not complete within {seconds}s (hang?)")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _words(value: str) -> list[str]:
    """Split `value` into word tokens on separators and lower->UPPER
    transitions (mirrors the boundary shapes matcher.py treats as identity
    boundaries: separator-delimited AND camelCase-joined)."""
    words: list[str] = []
    for chunk in _WORD_RE.findall(value):
        start = 0
        for i in range(1, len(chunk)):
            if chunk[i - 1].islower() and chunk[i].isupper():
                words.append(chunk[start:i])
                start = i
        words.append(chunk[start:])
    return [w for w in words if w]


def _variants(value: str) -> set[str]:
    words = _words(value)
    forms = {value, value.lower(), value.upper()}
    if words:
        for sep in _SEPARATORS:
            forms.add(sep.join(words))
            forms.add(sep.join(w.lower() for w in words))
            forms.add(sep.join(w.upper() for w in words))
            forms.add(sep.join(w.capitalize() for w in words))
        forms.add(words[0].lower() + "".join(w.capitalize() for w in words[1:]))
        forms.add("".join(w.capitalize() for w in words))
    return {f for f in forms if f}


def source_variants(source: Identity) -> set[str]:
    variants: set[str] = set()
    for value in source.as_dict_prompted().values():
        variants.update(_variants(value))
    return variants


def test_equality_class_preserved():
    source = replace(SOURCE, app_name="demo_widget")
    dest = synthesize_dest(source)
    assert dest.package_name == dest.app_name


def test_all_distinct_source_yields_all_distinct_dest():
    values = SOURCE.as_dict_prompted().values()
    assert len(set(values)) == len(values)  # fixture sanity: base case
    dest = synthesize_dest(SOURCE)
    dest_values = list(dest.as_dict_prompted().values())
    assert len(set(dest_values)) == len(dest_values)


def test_deterministic():
    assert synthesize_dest(SOURCE) == synthesize_dest(SOURCE)


def test_containment_free_vs_variants():
    variants = {v.lower() for v in source_variants(SOURCE) if v}
    dest = synthesize_dest(SOURCE)
    for value in dest.as_dict_prompted().values():
        lowered = value.lower()
        for variant in variants:
            assert variant not in lowered, (variant, value)
            assert lowered not in variant, (variant, value)


def test_every_synth_value_is_valid():
    dest = synthesize_dest(SOURCE)
    dest.validate()  # must not raise
    for field, value in dest.as_dict_prompted().items():
        VALIDATORS[field](value)  # must not raise


def test_cross_shape_equality_class_is_valid_for_all_its_fields():
    # author and email have DISJOINT charsets in general (identifier-style
    # fields forbid '@'/'.', email requires them) but author is otherwise
    # unrestricted, so author == email is a realizable equality class whose
    # shared dest value must satisfy BOTH validators simultaneously.
    source = replace(SOURCE, author=SOURCE.email)
    source.validate()  # fixture sanity: this source is itself valid
    dest = synthesize_dest(source)
    assert dest.author == dest.email
    VALIDATORS["author"](dest.author)
    VALIDATORS["email"](dest.email)


# --- regression: single-character source value used to hang forever -------
#
# `_safe_prefix` used to build every candidate as a HARDCODED "z" literal
# plus a sha256-derived suffix. Any source field whose ENTIRE value was "z"
# (a valid package_name/repo_name/app_name/owner value — all four allow a
# bare single lowercase letter) made `_collides` reject EVERY candidate
# unconditionally, forever: "z" is a substring of any "z...." string
# regardless of what follows it, so the retry loop's varying suffix never
# mattered. Verified 100% reproducible via SIGALRM before the fix. The
# leading letter is now derived from the hash itself (not a fixed literal),
# so a colliding letter is resolved by simply trying the next attempt.


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="SIGALRM POSIX-only")
@pytest.mark.parametrize("field", ["owner", "package_name", "app_name", "repo_name"])
def test_single_char_field_does_not_hang(field):
    source = replace(SOURCE, **{field: "z"})
    source.validate()  # fixture sanity: "z" is a valid value for this field
    with _bounded(5):
        dest = synthesize_dest(source)

    dest.validate()  # property 3: still valid
    dest_values = dest.as_dict_prompted()
    # property 2: "z" appears in exactly this one source field, so its dest
    # value must still be a singleton (no accidental equality introduced).
    assert list(dest_values.values()).count(dest_values[field]) == 1

    # property 4: containment-free vs every variant of the source value "z".
    lowered = dest_values[field].lower()
    for variant in {v.lower() for v in _variants("z")}:
        assert variant not in lowered
        assert lowered not in variant


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="SIGALRM POSIX-only")
def test_bounded_cap_raises_instead_of_hanging():
    # Pathological (but constructible) input: email's `local@domain.tld`
    # shape ALWAYS contains a literal "@" by construction. If some OTHER
    # source value is exactly "@", every producible email candidate
    # collides with it, forever, under the old unbounded `while True` loop.
    # The bounded retry now raises a clear, field-naming ValidationError
    # instead of hanging — defense-in-depth for inputs no amount of
    # hash-derived-letter cleverness can resolve (the "@" is structural,
    # not a leading-character choice).
    #
    # Was "." until dot segments became invalid author values (a rendered
    # "."/".." in a symlink target repoints the link at its own directory);
    # "@" reproduces the identical structural collision and is still valid.
    source = replace(SOURCE, author="@")
    source.validate()  # fixture sanity: "@" is a valid author value
    with _bounded(5), pytest.raises(ValidationError, match="email"):
        synthesize_dest(source)


class TestSynthDisplayName:
    def test_none_stays_none(self):
        assert synthesize_dest(_identity()).display_name is None

    def test_deterministic_two_word_title(self):
        src = _identity(display_name="Py Launch Blueprint")
        a = synthesize_dest(src)
        b = synthesize_dest(src)
        assert a.display_name == b.display_name
        words = a.display_name.split()
        assert len(words) == 2
        assert all(w.isalpha() for w in words)
        assert all(w[0].isupper() and w[1:].islower() for w in words)

    def test_display_containment_free_vs_source_variants(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = synthesize_dest(src)
        lowered = dst.display_name.lower()
        glued = lowered.replace(" ", "")
        for value in src.as_dict().values():
            v = value.lower().replace("_", "").replace("-", "").replace(" ", "")
            assert v not in glued and glued not in v

    def test_dest_validates(self):
        synthesize_dest(_identity(display_name="Py Launch Blueprint")).validate()

    def test_title_case_holds_for_digit_bearing_names(self):
        dst = synthesize_dest(_identity(display_name="Some Product 23"))
        words = dst.display_name.split()
        assert len(words) == 2
        assert all(w.isalpha() for w in words)
        assert all(w[0].isupper() and w[1:].islower() for w in words)


# --- issue #46: equality-signature preservation across derived slots -------
#
# `synthesize_dest`'s D6 guarantee ("two SOURCE slots with the same value
# get the same DEST value") originally covered only the 6 REQUIRED_FIELDS.
# Two other rewrite-row slots `_identity_rows` also emits went uncovered:
# `app_name_upper` (= app_name.upper()) and the three display_name_{spaced,
# pascal,camel} forms. A source where one of those derived slots
# COINCIDENTALLY equals another slot's value (e.g. app_name="press",
# display_name="Press" -- camel("Press")="press") made the synthetic
# destination, which has full freedom to avoid this, produce MISALIGNED
# values anyway, tripping pipeline.py's ambiguity guard on a perfectly
# ordinary source config. Verified empirically (session evidence, not
# asserted here) that the SAME guard correctly rejects a REAL press toward
# an operator's own unaligned destination -- so the guard itself is
# untouched; every fix below lives entirely in synthesize.py.
#
# "A clean verify proves the target can survive the generated coherent
# press. Every real press still validates its actual destination
# independently." -- a clean verify never certifies an unseen future
# destination; it only proves synthesize_dest's OWN probe is coherent.


class TestEqualitySignature:
    """Unit tests for the two-way postcondition itself."""

    def test_passes_on_an_aligned_pair(self):
        source = _identity(app_name="press", display_name="Press")
        dest = _identity(app_name="potato", display_name="Potato")
        _assert_equality_signature(source, dest)  # must not raise

    def test_raises_on_a_lost_source_equality(self):
        # source app_name == display_name_camel; dest breaks that tie.
        source = _identity(app_name="press", display_name="Press")
        dest = _identity(app_name="potato", display_name="Spud Tool")
        with pytest.raises(ValidationError, match="equality signature"):
            _assert_equality_signature(source, dest)

    def test_raises_on_a_new_dest_only_equality(self):
        # source slots are pairwise distinct; dest collapses two of them --
        # the class Codex constructed with ss-fold/titlecase display names,
        # reproduced here directly against the assertion in isolation.
        source = _identity(app_name="press", owner="acme")
        dest = _identity(app_name="potato", owner="potato")  # app == owner in dest only
        with pytest.raises(ValidationError, match="equality signature"):
            _assert_equality_signature(source, dest)


class TestSlotModel:
    def test_slot_values_includes_app_name_upper_and_display_forms(self):
        source = _identity(app_name="press", display_name="Press")
        slots = _slot_values(source)
        assert slots["app_name_upper"] == "PRESS"
        assert slots["display_spaced"] == "Press"
        assert slots["display_pascal"] == "Press"
        assert slots["display_camel"] == "press"

    def test_slot_values_omits_display_when_absent(self):
        slots = _slot_values(_identity())
        assert not any(k.startswith("display_") for k in slots)

    def test_is_entangled_requires_a_derived_member(self):
        # two REQUIRED_FIELDS sharing a value is NOT "entangled" in this
        # module's sense -- that's ordinary D6, handled by the ORIGINAL
        # classes/_synth_value path unchanged.
        assert not _is_entangled(["app_name", "package_name"])
        assert _is_entangled(["app_name", "app_name_upper"])
        assert _is_entangled(["owner", "display_camel"])
        assert not _is_entangled(["app_name_upper"])  # singleton, not entangled


class TestSourceSignature:
    """Direct unit coverage of the signature algebra the fallback candidate
    generator relies on -- derived and verified against real
    identity.display_forms() output, not guessed."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("9foo", (True, True, True)),  # digit-led: all three forms equal
            ("Press", (True, False, False)),  # upper-led: spaced == pascal only
            ("press", (False, True, False)),  # lower-led: spaced == camel only
            ("Some Product", (False, False, False)),  # multi-word, letter-led
            ("1st Place", (False, False, True)),  # multi-word, digit-led first word
            ("中文", (True, True, True)),  # uncased script: case-invariant
            ("@@", (True, True, True)),  # punctuation: case-invariant
        ],
    )
    def test_signature_matches_real_display_forms(self, value, expected):
        assert _source_signature(value) == expected
        forms = display_forms(value)
        sp_pa, sp_ca, pa_ca = expected
        assert (forms["spaced"] == forms["pascal"]) == sp_pa
        assert (forms["spaced"] == forms["camel"]) == sp_ca
        assert (forms["pascal"] == forms["camel"]) == pa_ca


class TestMaskedCandidates:
    """Change #3: the search must not be falsely-exhaustible -- proven here
    by exhaustively enumerating a small family and checking every value in
    it is actually visited exactly once (a true bijection), not a
    with-replacement sample that can miss members."""

    def test_bijection_over_a_small_family(self):
        display = "go"  # two lowercase letters: family size 26*26 = 676
        positions = _mask_positions(display)
        assert len(positions) == 2
        candidates = list(_masked_candidates(display))
        assert len(candidates) == 676
        assert len(set(candidates)) == 676  # every value distinct: no repeats
        # every candidate is a real permutation of the same two-letter shape
        assert all(len(c) == 2 and c.isalpha() and c.islower() for c in candidates)

    def test_non_maskable_characters_are_preserved_verbatim(self):
        display = "ß-9"  # ß is excluded (upper() changes length); '-' inert
        candidates = list(_masked_candidates(display))
        assert candidates  # the '9' alone still yields a (small) family
        for c in candidates:
            assert c[0] == "ß"
            assert c[2] == "9" or c[2].isdigit()  # only the digit varies
            assert c[1] == "-"

    def test_fully_unmaskable_source_yields_no_masked_candidates(self):
        assert list(_masked_candidates("中文")) == []
        assert list(_masked_candidates("@@")) == []

    def test_deterministic(self):
        assert list(_masked_candidates("widget")) == list(_masked_candidates("widget"))


class TestFallbackCandidates:
    """Change #4: candidates for sources whose tier-1 family is degenerate
    (uncased scripts, pure punctuation) or exhausted."""

    def test_single_word_all_equal_signature_is_digit_led(self):
        first = next(iter(_fallback_candidates("中文")))
        assert first[0].isdigit()
        sp, pa, ca = _source_signature(first)
        assert (sp, pa, ca) == (True, True, True)

    def test_single_word_upper_led_signature(self):
        first = next(iter(_fallback_candidates("Press")))
        assert first[0].isupper()
        assert _source_signature(first) == (True, False, False)

    def test_single_word_lower_led_signature(self):
        first = next(iter(_fallback_candidates("press")))
        assert first[0].islower()
        assert _source_signature(first) == (False, True, False)

    def test_multi_word_invariant_led_signature(self):
        first = next(iter(_fallback_candidates("中 文")))
        assert " " in first
        assert _source_signature(first) == (False, False, True)

    def test_multi_word_all_distinct_signature(self):
        first = next(iter(_fallback_candidates("Some Product")))
        assert " " in first
        assert _source_signature(first) == (False, False, False)

    def test_candidates_are_distinct_and_deterministic(self):
        a = list(islice(_fallback_candidates("@@"), 20))
        b = list(islice(_fallback_candidates("@@"), 20))
        assert a == b
        assert len(set(a)) == len(a)


class TestSynthesizeEntangled:
    """End-to-end: synthesize_dest on sources whose derived slots collide."""

    def test_the_issues_own_case_camel_vs_app_name(self):
        source = _identity(app_name="press", display_name="Press")
        dest = synthesize_dest(source)
        assert display_forms(dest.display_name)["camel"] == dest.app_name
        dest.validate()

    def test_app_name_upper_vs_owner_no_display_involved(self):
        source = _identity(app_name="press", owner="PRESS")
        dest = synthesize_dest(source)
        assert dest.app_name.upper() == dest.owner
        dest.validate()

    def test_backward_propagation_display_and_upper_share_one_class(self):
        # app_name_upper AND both display spaced/pascal collide on "PRESS"
        # simultaneously -- the case that defeats independent sequential
        # solving and requires display -> upper -> app_name propagation.
        source = _identity(app_name="press", owner="PRESS", display_name="PRESS")
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert forms["spaced"] == dest.owner == dest.app_name.upper()
        dest.validate()

    def test_multiple_independent_classes_simultaneously(self):
        # "Press" is sig2 (spaced == pascal, both distinct from camel) --
        # exactly two independent equality groups: camel alone, and
        # spaced/pascal together. app_name (tied via camel) and owner (tied
        # via the spaced/pascal group) must therefore resolve as two
        # GENUINELY separate classes within the SAME candidate search, each
        # getting its own distinct dest value -- proving step 2's per-form
        # proposal-building keeps multiple simultaneous classes coherent,
        # not just the single-class case the other tests cover.
        source = _identity(app_name="press", owner="Press", display_name="Press")
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert forms["camel"] == dest.app_name
        assert forms["pascal"] == forms["spaced"] == dest.owner
        assert dest.app_name != dest.owner  # two DISTINCT classes stay distinct
        dest.validate()

    def test_email_author_and_display_all_identical(self):
        source = _identity(
            author="demo@example.com",
            email="demo@example.com",
            display_name="demo@example.com",
        )
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert dest.author == dest.email == forms["spaced"] == forms["camel"]
        dest.validate()
        VALIDATORS["email"](dest.email)
        VALIDATORS["author"](dest.author)

    def test_tied_ss_fold_display_stays_containment_free_and_coherent(self):
        source = _identity(author="ßfoo", display_name="ßfoo")
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert forms["spaced"] == dest.author

    def test_tied_titlecase_display_stays_containment_free_and_coherent(self):
        source = _identity(author="ǅfoo", display_name="ǅfoo")
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert forms["spaced"] == dest.author

    def test_uncased_script_display_tied_to_author(self):
        source = _identity(author="中文", display_name="中文")
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert forms["spaced"] == forms["pascal"] == forms["camel"] == dest.author
        dest.validate()

    def test_punctuation_only_display_tied_to_author(self):
        source = _identity(author="@@", display_name="@@")
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert forms["spaced"] == forms["pascal"] == forms["camel"] == dest.author
        dest.validate()

    def test_untied_ss_fold_display_takes_the_unchanged_fast_path(self):
        # all-distinct source signature (untied) -- no entanglement at all,
        # so this must produce byte-identical output to the pre-#46 code
        # path and the postcondition must not overfire on exotic-but-benign
        # sources.
        source = _identity(display_name="ßfoo Bar")
        dest = synthesize_dest(source)
        dest.validate()
        words = dest.display_name.split()
        assert len(words) == 2  # today's two-word Title-Case shape, unchanged

    def test_single_word_display_now_coherent_not_silently_dropped(self):
        # Deliberate behavior change (flagged in the commit message): a
        # single-word display has source spaced == pascal (an entangled
        # pair of two derived slots), so it now takes the entangled path
        # and gets a signature-matched single-word dest -- previously it
        # silently survived only because pipeline.py's ambiguity_family
        # winner-drop discarded one of the two conflicting rows.
        source = _identity(display_name="Blueprint")
        dest = synthesize_dest(source)
        forms = display_forms(dest.display_name)
        assert forms["spaced"] == forms["pascal"]
        dest.validate()

    def test_deterministic_on_the_entangled_path(self):
        source = _identity(app_name="press", display_name="Press")
        assert synthesize_dest(source) == synthesize_dest(source)

    def test_owner_length_cap_respected_when_entangled(self):
        source = _identity(app_name="press", owner="PRESS")
        dest = synthesize_dest(source)
        assert len(dest.owner) <= 39
        dest.validate()


def test_non_entangled_source_is_byte_identical_to_the_original_algorithm():
    # Zero-regression contract: a source with no derived-slot collision at
    # all must produce EXACTLY what the pre-#46 implementation produced --
    # captured once (before this change existed) and pinned here as a
    # golden constant, so any accidental widening of the "entangled"
    # detection is caught immediately.
    source = _identity(display_name="Py Launch Blueprint")
    dest = synthesize_dest(source)
    assert dest == Identity(
        package_name="f057575b386ea2c7046daf38",
        repo_name="f057575b3806d3d7cd038176",
        app_name="f057575b389c80238a4111d4",
        author="f057575b382dedff56242293",
        email="f057575b38ad32ff@4ad86d6ede.7c9",
        owner="f057575b38bd6ae1be249151",
        display_name="Pzepwb Jtsxlj",
    )


class TestSynthesizeAgainstThePipelineGuard:
    """Proof that #46 changes only `synthesize.py`'s OUTPUT, never
    `pipeline.py`'s guard: the guard rejects a real operator's unaligned
    destination exactly as before, and accepts every entangled-source
    synthetic destination this module now produces -- through the SAME
    `compile_substitution_table` call `press verify`/`press rebrand`
    actually run, not a hand-rolled check."""

    SOURCE = Identity(
        package_name="demo_widget",
        repo_name="demo-widget",
        app_name="press",
        author="Demo Author",
        email="demo@example.com",
        owner="demolabs",
        display_name="Press",
    )

    def _compile(self, destination: Identity):
        return compile_substitution_table(
            self.SOURCE,
            destination,
            DEFAULT_RULES,
            SurfaceSnapshot(entries=(), visibility_inputs=()),
        )

    def test_real_unaligned_destination_still_rejected(self):
        # app_name="potato" but camel("Spud Tool")="spudTool" != "potato" --
        # an operator's own unaligned choice, nothing to do with synthesize.
        unaligned = Identity(
            package_name="potato_launcher",
            repo_name="potato-launcher",
            app_name="potato",
            author="Potato Farmer",
            email="potato@example.com",
            owner="potatolabs",
            display_name="Spud Tool",
        )
        with pytest.raises(ValidationError, match="different destinations"):
            self._compile(unaligned)

    def test_real_aligned_destination_still_accepted(self):
        aligned = Identity(
            package_name="potato_launcher",
            repo_name="potato-launcher",
            app_name="potato",
            author="Potato Farmer",
            email="potato@example.com",
            owner="potatolabs",
            display_name="Potato",
        )
        self._compile(aligned)  # must not raise

    def test_synthesized_destination_compiles_clean(self):
        # The issue's own case, through the REAL compiler path.
        dest = synthesize_dest(self.SOURCE)
        self._compile(dest)  # must not raise

    def test_synthesized_app_upper_case_compiles_clean(self):
        source = replace(self.SOURCE, display_name=None, owner="PRESS")
        dest = synthesize_dest(source)
        compile_substitution_table(
            source,
            dest,
            DEFAULT_RULES,
            SurfaceSnapshot(entries=(), visibility_inputs=()),
        )  # must not raise
