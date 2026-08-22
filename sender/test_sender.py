import unittest
from datetime import datetime, timedelta, timezone

from sender import sender


class NearbyReminderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 22, 7, 0, tzinfo=timezone.utc)

    def iso_minutes_ago(self, minutes):
        return (self.now - timedelta(minutes=minutes)).isoformat()

    def test_waits_until_ten_minutes(self):
        self.assertFalse(sender.nearby_reminder_due(
            "10", "10", self.iso_minutes_ago(9), now=self.now))
        self.assertTrue(sender.nearby_reminder_due(
            "10", "10", self.iso_minutes_ago(10), now=self.now))

    def test_only_runs_in_nearest_band(self):
        self.assertFalse(sender.nearby_reminder_due(
            "20", "20", self.iso_minutes_ago(15), now=self.now))
        self.assertFalse(sender.nearby_reminder_due(
            "10", "20", self.iso_minutes_ago(15), now=self.now))

    def test_does_not_repeat_after_reminder(self):
        self.assertFalse(sender.nearby_reminder_due(
            "10:reminded", "10", self.iso_minutes_ago(30), now=self.now))
        self.assertEqual(sender._as_band("10:reminded"), 10)

    def test_message_is_explicit(self):
        title, body = sender.build_message("nearby_still", 6.2)
        self.assertIn("10km 안", title)
        self.assertIn("계속 관측", body)


if __name__ == "__main__":
    unittest.main()
