import unittest

from ticket import normalize_ticket_reference


class TicketTests(unittest.TestCase):
    def test_valid(self):
        for source, target in (("al-1", "AL-1"), (" AL-42\n", "AL-42"), ("Al-999999", "AL-999999")):
            with self.subTest(source=source):
                self.assertEqual(normalize_ticket_reference(source), target)

    def test_invalid(self):
        for source in ("AL-0", "AL-01", "AL-1000000", "AL-3x", "AL--1", ""):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    normalize_ticket_reference(source)


if __name__ == "__main__":
    unittest.main()
