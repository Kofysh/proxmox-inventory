import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import proxmox_inventory as app
from test_inventory import FIXTURE


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.report = app.build_report(FIXTURE['nodes'], FIXTURE['resources'], 'demo', 'fictif')

    def test_first_then_changed_collection_preserve_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, delta = app.save_history(self.report, tmp)
            original = (first / 'inventory.json').read_bytes()
            self.assertIsNone(delta)
            self.assertFalse((first / 'comparison.json').exists())
            after = copy.deepcopy(self.report)
            after['generated_at'] = '2099-01-01T00:00:00+00:00'
            after['guests'][0]['status'] = 'stopped'
            second, delta = app.save_history(after, tmp)
            self.assertNotEqual(first, second)
            self.assertTrue(delta['has_changes'])
            self.assertEqual((first / 'inventory.json').read_bytes(), original)
            self.assertTrue(json.loads((second / 'comparison.json').read_text(encoding='utf-8'))['has_changes'])
            self.assertEqual(len(list(Path(tmp).glob('run-*'))), 2)

    def test_mixed_sources_modes_and_clock_rollback_are_rejected(self):
        for change in [dict(source='another'), dict(mode='live', scope='resources_visible_to_token'),
                       dict(generated_at='2000-01-01T00:00:00+00:00')]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                app.save_history(self.report, tmp)
                with self.assertRaises(app.InventoryError):
                    app.save_history(dict(self.report, **change), tmp)
                self.assertEqual(len(list(Path(tmp).glob('run-*'))), 1)
                self.assertFalse((Path(tmp) / '.inventory.lock').exists())

    def test_same_timestamp_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, _ = app.save_history(self.report, tmp)
            second, delta = app.save_history(self.report, tmp)
            self.assertNotEqual(first, second)
            self.assertFalse(delta['has_changes'])

    def test_lock_blocks_writer_without_removing_existing_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / '.inventory.lock'
            lock.touch()
            with self.assertRaisesRegex(app.InventoryError, 'verrouillé'):
                app.save_history(self.report, tmp)
            self.assertTrue(lock.exists())
            self.assertEqual(list(Path(tmp).glob('run-*')), [])

    def test_failed_write_never_publishes_partial_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app.save_history(self.report, tmp)
            writer = app.write_report
            def fail_comparison(report, output):
                if Path(output).name == 'comparison.json':
                    raise app.InventoryError('écriture simulée')
                writer(report, output)
            with patch.object(app, 'write_report', side_effect=fail_comparison), self.assertRaises(app.InventoryError):
                app.save_history(self.report, tmp)
            self.assertEqual(len(list(Path(tmp).glob('run-*'))), 1)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_corrupt_latest_report_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, _ = app.save_history(self.report, tmp)
            (folder / 'inventory.json').write_text('invalid')
            with self.assertRaises(app.InventoryError):
                app.save_history(self.report, tmp)
            self.assertEqual(len(list(Path(tmp).glob('run-*'))), 1)

    def test_quiet_cli_and_filters_preserve_complete_history(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.stdout', new_callable=io.StringIO) as output:
            for _ in range(2):
                self.assertEqual(app.main(['--demo', '--history', tmp, '--quiet', '--status', 'running']), 0)
            folders = sorted(Path(tmp).glob('run-*'))
            report = json.loads((folders[-1] / 'inventory.json').read_text(encoding='utf-8'))
            self.assertEqual(len(report['guests']), 4)
            self.assertTrue((folders[-1] / 'comparison.json').exists())
            self.assertEqual(output.getvalue(), '')

    def test_incompatible_options_fail_before_network(self):
        for options in [['--check'], ['--output', 'report.json'], ['--compare', 'a', 'b']]:
            with self.subTest(options=options), patch.object(app, 'ProxmoxClient') as client, \
                    patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:
                    app.main(['--history', *options])
                self.assertEqual(caught.exception.code, 2)
                client.assert_not_called()
