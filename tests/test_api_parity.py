"""Facade API parity gate.

emc2101.mp and emc2101.cp must export an identical public surface
(__all__, same names in the same order), with every name resolvable on
both modules. This enforces the "one package, one API" promise (decision
D3) across the MicroPython and CPython facades.
"""
import unittest

import emc2101
import emc2101.cp as cp_mod
import emc2101.mp as mp_mod


class ApiParityTestCase(unittest.TestCase):
    def test_all_lists_are_identical_including_order(self):
        self.assertEqual(list(mp_mod.__all__), list(cp_mod.__all__))

    def test_all_list_is_nonempty_and_unique(self):
        self.assertGreater(len(mp_mod.__all__), 0)
        self.assertEqual(len(set(mp_mod.__all__)), len(mp_mod.__all__))

    def test_every_exported_name_resolves_on_both_facades(self):
        for name in mp_mod.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(mp_mod, name), name)
                self.assertTrue(hasattr(cp_mod, name), name)

    def test_device_class_present_on_both_facades(self):
        self.assertTrue(hasattr(mp_mod, "EMC2101"))
        self.assertTrue(hasattr(cp_mod, "EMC2101"))

    def test_package_version_string(self):
        self.assertIsInstance(emc2101.__version__, str)
        self.assertRegex(emc2101.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
