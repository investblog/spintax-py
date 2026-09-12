"""The `Typing :: Typed` classifier is a promise, and one empty file keeps it.

Without `py.typed` a type checker will not read our annotations at all — it reports
`module is installed, but missing library stubs or py.typed marker` and then treats
every call as `Any`. Measured on a real consumer against a real wheel: with the marker,
`--strict` mypy catches both a wrong return type and an unknown keyword argument;
with the marker deleted and nothing else changed, both findings disappear.

So the classifier without the file is worse than neither. It tells downstream users
their misuse will be caught, and it silently will not be.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import spintax_core


def _classifiers() -> list[str]:
    """Read the classifiers the DISTRIBUTION declares, not the ones pyproject.toml says.

    Two reasons, and the first one bit: `tomllib` is stdlib only from 3.11, while this
    package supports 3.10, so parsing the source file broke collection on the oldest
    interpreter we promise to run on. The second is the better one — installed metadata
    is what a consumer's tooling actually reads, so asserting against it tests the claim
    that reaches users rather than the file it was written in.
    """
    raw = metadata.metadata("spintax-core").get_all("Classifier") or []
    return [str(c) for c in raw]


def test_the_marker_sits_beside_the_module_that_is_imported() -> None:
    """Checked against `__file__`, not a hard-coded path.

    Under an editable install that is the source tree; under a wheel it is the installed
    package. Either way it is the copy a consumer's type checker would actually look in.
    """
    assert (Path(spintax_core.__file__).parent / "py.typed").is_file()


def test_the_marker_is_empty() -> None:
    """PEP 561 defines it as a marker. Content would be a partial-stub declaration we
    are not making, and a linter stripping the file to nothing must not read as damage."""
    assert (Path(spintax_core.__file__).parent / "py.typed").read_bytes() == b""


def test_the_classifier_and_the_marker_agree() -> None:
    """Either claim can be dropped — but never only one of them.

    Removing the classifier and keeping the file is fine (the file is what does the
    work). Keeping the classifier without the file is the defect this pins.
    """
    if "Typing :: Typed" in _classifiers():
        assert (Path(spintax_core.__file__).parent / "py.typed").is_file(), (
            "pyproject.toml claims Typing :: Typed but py.typed is missing — "
            "downstream type checkers will ignore every annotation in this package"
        )


def test_the_readme_does_not_pin_a_corpus_count() -> None:
    """The README is the PyPI long description, and PyPI descriptions are immutable per
    release — a number written here can only be corrected by shipping a version.

    This is a guard against a recurrence, not a hypothetical. The README said "All 168 of
    them pass" and "168 corpus fixtures pass" while the corpus stood at 277, and the
    GitHub repository description carried the same stale number; one release earlier the
    description still read "Pre-code: spec only", three versions after the engine shipped.
    The shelf-facing surface drifts precisely because nothing reads it.

    So: state the property, never the count. "Every corpus fixture passes, 0 xfailed,
    0 skipped" stays true as the corpus grows; "168 fixtures pass" is a claim with a
    shelf life. Release notes and commit messages are the right home for a number, since
    both are point-in-time records.

    Deliberately narrow — it matches a digit that *modifies* the word, so prose like
    "gated by the shared golden corpus" is untouched and only a count trips it.
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    pinned = re.findall(r"\b\d[\d,\s]*(?=\s*(?:corpus\s+)?fixtures?\b)", readme, re.IGNORECASE)
    pinned += re.findall(r"(?<=\bAll\s)\d+\b", readme)

    assert not pinned, (
        f"README.md pins a fixture count ({pinned}); it ships to PyPI immutably and has "
        "gone stale twice. State the property instead — see this test's docstring."
    )
