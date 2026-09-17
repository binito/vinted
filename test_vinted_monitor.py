import time
import unittest

from vinted_monitor import hora_relatorio_valida, relatorio_em_falta


class DailyReportScheduleTests(unittest.TestCase):
    def test_accepts_valid_report_time(self):
        self.assertTrue(hora_relatorio_valida("09:00"))
        self.assertTrue(hora_relatorio_valida("23:59"))
        self.assertFalse(hora_relatorio_valida("9:00"))
        self.assertFalse(hora_relatorio_valida("24:00"))

    def test_report_is_due_only_once_per_day(self):
        now = time.strptime("2026-09-17 09:00", "%Y-%m-%d %H:%M")
        self.assertTrue(relatorio_em_falta({}, "09:00", now))
        self.assertFalse(relatorio_em_falta({"last_daily_report": "2026-09-17"}, "09:00", now))
        self.assertFalse(relatorio_em_falta({}, "09:01", now))


if __name__ == "__main__":
    unittest.main()
