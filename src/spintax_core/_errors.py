"""The exceptions this engine raises — all of them about the CALLER, never the template.

Rendering is lenient by contract (§9.2): malformed markup degrades, it does not raise.
So nothing here fires because of what a template says. `AstVersionError` means a handle
came from a different engine version, and `IncludeResolverError` means a callback the
host supplied threw. Both are programmer errors, and both would otherwise surface as a
mystery `AttributeError` or as the host's own exception arriving from inside a render.

Names mirror the reference's, deliberately. No fixture requires them — every remaining
corpus case is `op: render` or `op: neutralize` and not one asserts a throw — so this is
a local decision, and the ecosystem's value is one mental model across three engines.
Somebody moving between the TypeScript and Python packages should not have to learn a
second vocabulary for the same two failures.

`NotImplementedError` is the exception the reference defines that this port does not:
Python has one built in, and shadowing a builtin to gain nothing would be a poor trade.
"""

from __future__ import annotations


class SpintaxError(Exception):
    """Base class for every error this engine raises. Catch this to catch them all.

    One caveat while P2 is unfinished: the reference makes its `NotImplementedError` a
    subclass of this, and the port uses Python's builtin instead, so the unbuilt
    post-process stage escapes `except SpintaxError`. That is today's most likely
    exception by far, and it disappears when step 7 lands.
    """


class AstVersionError(SpintaxError):
    """An `Ast` handle was not produced by this engine version.

    Raised rather than tolerated because the alternative is silent and worse: an `Ast`
    built before `AST_VERSION` 2 carries no `#def` map, so rendering it would quietly
    drop every definition and produce plausible output that is wrong.
    """


class IncludeResolverError(SpintaxError):
    """A host-supplied `include_resolver` raised.

    Deliberately NOT swallowed into the lenient path. A resolver that cannot find a
    template returns `None` and the include renders empty; a resolver that *throws* has a
    bug in it, and hiding that behind an empty string would make it undebuggable.
    """
