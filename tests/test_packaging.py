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
