"""API coverage gate: assert every public member of the package is
referenced somewhere in the unit-test suite under tests/.

Covered surface (M3 onward):
  - every name exported by both facades (emc2101.mp.__all__ /
    emc2101.cp.__all__), and
  - every public attribute of the device class (dir(EMC2101) minus
    underscore-prefixed names), i.e. methods and properties.

Run: python tools/api_coverage.py
Exits non-zero listing any uncovered names."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import emc2101.cp as cp_mod  # noqa: E402
import emc2101.mp as mp_mod  # noqa: E402


def main():
    if list(mp_mod.__all__) != list(cp_mod.__all__):
        print("facade __all__ lists differ (run the test suite first)")
        return 1
    names = set(mp_mod.__all__)
    names.update(n for n in dir(mp_mod.EMC2101) if not n.startswith("_"))

    test_src = ""
    tests_dir = os.path.join(ROOT, "tests")
    for fn in sorted(os.listdir(tests_dir)):
        if fn.startswith("test_") and fn.endswith(".py"):
            with open(os.path.join(tests_dir, fn), encoding="utf-8") as f:
                test_src += f.read() + "\n"

    missing = [n for n in sorted(names)
               if not re.search(r"\b" + re.escape(n) + r"\b", test_src)]
    total = len(names)
    print("public members: %d (%d facade exports + %d class members)"
          % (total, len(set(mp_mod.__all__)),
             len([n for n in dir(mp_mod.EMC2101)
                  if not n.startswith("_")])))
    if missing:
        print("NOT EXERCISED IN TEST SUITE:")
        for m in missing:
            print("  - %s" % m)
        return 1
    print("api coverage: 100%% (all %d public members exercised)" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
