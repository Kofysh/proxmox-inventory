from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import proxmox_inventory as app


class PresentationTests(unittest.TestCase):
    def test_paris_summer_and_winter(self):
        try:
            ZoneInfo('Europe/Paris')
        except ZoneInfoNotFoundError:
            self.skipTest('Base de fuseaux absente ; le repli UTC est testé séparément.')
        self.assertIn('14:00:00 (Paris, UTC+02:00)', app.display_date('2026-07-01T12:00:00+00:00'))
        self.assertIn('13:00:00 (Paris, UTC+01:00)', app.display_date('2026-01-01T12:00:00+00:00'))

    def test_missing_timezone_database_falls_back_to_explicit_utc(self):
        with patch.object(app, 'ZoneInfo', side_effect=ZoneInfoNotFoundError):
            self.assertIn('12:00:00 UTC (fuseau Paris indisponible)', app.display_date('2026-07-01T12:00:00+00:00'))

    def test_age_boundaries_and_future(self):
        now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        for stamp, expected in [('12:00:00', 'moins d’une minute'), ('11:59:00', '1 minute'),
                                ('11:58:00', '2 minutes'), ('11:00:00', '1 heure'),
                                ('10:00:00', '2 heures'), ('12:01:00', 'futur')]:
            self.assertIn(expected, app.report_age('2026-10-13T'+stamp+'+00:00', now))
        self.assertIn('1 jour', app.report_age('2026-10-12T12:00:00+00:00', now))
        self.assertIn('indisponible', app.report_age('invalide', now))

    def test_natural_plurals(self):
        self.assertEqual(app.count_label(0, 'Modèle'), '0 Modèle')
        self.assertEqual(app.count_label(1, 'Nœud'), '1 Nœud')
        self.assertEqual(app.count_label(16, 'Invité'), '16 Invités')
