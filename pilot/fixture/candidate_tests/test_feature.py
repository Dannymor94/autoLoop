"""Expected RED on baseline; all candidates must fix the same feature."""

from __future__ import annotations

import unittest

from toy_app import slugify


class SlugifyAcceptanceTests(unittest.TestCase):
    def test_standard(self) -> None:
        self.assertEqual(slugify(" Hello   WORLD 42 "), "hello-world-42")

    def test_hyphens(self) -> None:
        self.assertEqual(slugify("--Already---slug--"), "already-slug")

    def test_empty(self) -> None:
        self.assertEqual(slugify("\t \n"), "")

    def test_non_ascii_rejected(self) -> None:
        with self.assertRaises(ValueError):
            slugify("файл")

    def test_type_rejected(self) -> None:
        with self.assertRaises(TypeError):
            slugify(42)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
