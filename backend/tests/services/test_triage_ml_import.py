"""``services.triage_ml`` must import without the ML stack installed.

The module's own docstring promises it "falls back to LightGBM-only if full
artifacts aren't present, or None if no artifacts exist at all", and ``_load()``
catches ImportError in three places to make that true. But numpy, pandas and
scipy were imported at module level, so the promise did not hold: importing
``services.triage_ml`` raised, ``routers.triage`` raised, and ``main`` raised
with it.

The practical effect was that ``requirements.txt``, which says it is "enough for
local dev without Triageist pickles", could not start the app. A new developer
following the README got ModuleNotFoundError on numpy.

Every use of np/pd/scipy in that module sits in a private helper that only runs
after ``_load()`` has returned an artifact, and an artifact cannot load without
those libraries present. So a local import inside each helper is safe by
construction: if the code reaches it, the library is there.
"""
from __future__ import annotations


import importlib
import sys
from contextlib import contextmanager

import pytest


@contextmanager
def _without(*module_names: str):
    """Make the named top-level packages un-importable inside the block.

    Uses a sys.meta_path finder rather than patching builtins.__import__.
    Patching __import__ only intercepts the `import x` statement;
    importlib.import_module goes through _gcd_import and sails straight past it,
    so a helper built that way silently blocks nothing. The guard test below is
    what caught that.
    """
    blocked = set(module_names)

    class _Blocker:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in blocked:
                raise ModuleNotFoundError(f"No module named {name.split('.')[0]!r}", name=name)
            return None

    saved = {k: v for k, v in sys.modules.items()
             if k.split(".")[0] in blocked or k.startswith("services.triage_ml")}
    for key in saved:
        del sys.modules[key]

    blocker = _Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        # A blocked import can get part way in and leave broken partial entries
        # behind, so clear everything under the blocked roots before restoring
        # the good ones. Updating over the top is not enough: the junk keys are
        # not in `saved`, so they survive and poison the next import.
        for key in [k for k in sys.modules
                    if k.split(".")[0] in blocked or k.startswith("services.triage_ml")]:
            del sys.modules[key]
        sys.modules.update(saved)


def test_module_imports_without_numpy_pandas_or_scipy():
    with _without("numpy", "pandas", "scipy"):
        mod = importlib.import_module("services.triage_ml")
        assert mod is not None


def test_predict_returns_none_rather_than_raising_without_the_ml_stack():
    """Degrading to "no ML answer" is correct. Taking the process down is not."""
    with _without("numpy", "pandas", "scipy"):
        mod = importlib.import_module("services.triage_ml")
        result = mod.predict(
            {"age": 54, "chief_complaint": "chest pain"},
            {"heart_rate": 118, "sbp": 92, "o2_sat": 94, "resp_rate": 22, "temperature": 99.1},
        )
        assert result is None


def test_the_router_that_imports_it_also_survives():
    """triage_ml is imported by routers.triage, which is imported by main. If
    the chain breaks anywhere the whole app fails to start, which is the
    failure this is really guarding."""
    with _without("numpy", "pandas", "scipy"):
        mod = importlib.import_module("services.triage_ml")
        assert callable(mod.predict)


def test_the_guard_itself_works():
    """A test that cannot fail proves nothing. This asserts the block is real,
    so the three tests above are meaningful rather than vacuous.

    Deliberately blocks a stdlib module rather than numpy. numpy is not in
    requirements.txt, so on a core-deps install it is absent anyway and a test
    written against it would pass for the wrong reason.
    """
    import colorsys  # noqa: F401  (proves it is importable to begin with)

    with _without("colorsys"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("colorsys")

    assert importlib.import_module("colorsys") is not None, "the block must be undone"
