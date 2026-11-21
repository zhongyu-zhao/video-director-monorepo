from __future__ import annotations

import unittest

from auto_shot.taxonomy import validate_label_values


class TaxonomyTest(unittest.TestCase):
    def test_accepts_unknown_values(self) -> None:
        labels = {
            "scale": "unknown",
            "angle": "unknown",
            "camera": "unknown",
            "composition": "unknown",
            "lighting": "unknown",
            "color": "unknown",
            "dof": "unknown",
        }
        self.assertEqual(validate_label_values(labels), [])

    def test_reports_missing_and_invalid_values(self) -> None:
        labels = {
            "scale": "super-close",
            "angle": "eye-level",
            "camera": "unknown",
            "composition": "centered",
            "lighting": "low-key",
            "color": "cool",
        }
        errors = validate_label_values(labels)

        self.assertTrue(any("scale" in error for error in errors))
        self.assertTrue(any("dof" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
