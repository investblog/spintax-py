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

import tomllib
from pathlib import Path

import spintax_core

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _classifiers() -> list[str]:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["classifiers"]


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
