import errno
import io
import json
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

import proxmox_inventory as app
from test_inventory import ENV, FIXTURE
import test_inventory


class DiagnosticTests(unittest.TestCase):
    def test_network_causes_are_classified_without_private_details(self):
        cases = [
            (socket.gaierror(-2, 'private-secret'), 'DNS'),
            (ConnectionRefusedError(errno.ECONNREFUSED, 'private-secret'), 'refusée'),
            (TimeoutError('private-secret'), 'délai'),
            (ssl.SSLCertVerificationError(1, 'private-secret'), 'certificat'),
            (ssl.SSLError('private-secret'), 'TLS'),
            (OSError(errno.ENETUNREACH, 'private-secret'), 'inaccessible'),
            (ConnectionResetError('private-secret'), 'interrompue'),
        ]
        for error, expected in cases:
            for wrapped in (error, URLError(error)):
                with self.subTest(error=type(error).__name__, wrapped=isinstance(wrapped, URLError)):
                    client = test_inventory.InventoryTests().fake_client(b'')
                    client.opener.open.side_effect = wrapped
                    with self.assertRaises(app.InventoryError) as caught:
                        client.get('/nodes')
                    self.assertIn(expected, str(caught.exception))
                    self.assertNotIn('private-secret', str(caught.exception))

    def test_check_uses_both_routes_without_writing(self):
        with patch.object(app, 'ProxmoxClient') as client, patch.object(app, 'write_report') as writer, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            client.return_value.get.side_effect = [FIXTURE['nodes'], FIXTURE['resources']]
            client.return_value.base_url = ENV['PVE_URL']
            self.assertEqual(app.main(['--check']), 0)
            self.assertEqual([c.args[0] for c in client.return_value.get.call_args_list],
                             ['/nodes', '/cluster/resources?type=vm'])
            writer.assert_not_called()
            self.assertIn('aucun fichier créé', output.getvalue())
            self.assertIn('exhaustivité', output.getvalue())

    def test_empty_check_reports_visibility_limit(self):
        with patch.object(app, 'ProxmoxClient') as client, patch('sys.stdout', new_callable=io.StringIO) as output:
            client.return_value.get.side_effect = [[], []]
            client.return_value.base_url = ENV['PVE_URL']
            self.assertEqual(app.main(['--check']), 0)
            self.assertIn('Aucun nœud visible', output.getvalue())

    def test_check_rejects_invalid_data_and_identifies_stage(self):
        with patch.object(app, 'ProxmoxClient') as client, patch('sys.stdout', new_callable=io.StringIO), \
                patch('sys.stderr', new_callable=io.StringIO) as error:
            client.return_value.get.side_effect = [FIXTURE['nodes'], [{'type': 'bad'}]]
            self.assertEqual(app.main(['--check']), 1)
            self.assertIn('Validation des données', error.getvalue())

    def test_check_stops_on_first_failed_route(self):
        with patch.object(app, 'ProxmoxClient') as client, patch('sys.stdout', new_callable=io.StringIO) as output, \
                patch('sys.stderr', new_callable=io.StringIO) as error:
            client.return_value.get.side_effect = app.InventoryError('HTTP 401 : authentification refusée')
            self.assertEqual(app.main(['--check', '--quiet']), 1)
            self.assertEqual(client.return_value.get.call_count, 1)
            self.assertEqual(output.getvalue(), '')
            self.assertIn('API des nœuds', error.getvalue())
            self.assertIn('401', error.getvalue())

    def test_check_invalid_combinations_fail_before_network(self):
        for option in [['--demo'], ['--output', 'test.json'], ['--node', 'pve'],
                       ['--status', 'running'], ['--compare', 'a', 'b']]:
            with self.subTest(option=option), patch.object(app, 'ProxmoxClient') as client, \
                    patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:
                    app.main(['--check', *option])
                self.assertEqual(caught.exception.code, 2)
                client.assert_not_called()

    def test_quiet_inventory_and_comparison_still_export(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.stdout', new_callable=io.StringIO) as output:
            before, after, diff = [Path(tmp) / name for name in ['before.json', 'after.json', 'diff.json']]
            for path in (before, after):
                self.assertEqual(app.main(['--demo', '--quiet', '--output', str(path)]), 0)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['mode'], 'demo')
            self.assertEqual(app.main(['--compare', str(before), str(after), '--quiet', '--output', str(diff)]), 0)
            self.assertFalse(json.loads(diff.read_text(encoding='utf-8'))['has_changes'])
            self.assertEqual(output.getvalue(), '')

    def test_quiet_retains_configuration_errors(self):
        with patch.dict('os.environ', {}, clear=True), patch('sys.stdout', new_callable=io.StringIO) as output, \
                patch('sys.stderr', new_callable=io.StringIO) as error:
            self.assertEqual(app.main(['--quiet']), 1)
            self.assertEqual(output.getvalue(), '')
            self.assertIn('Configurer', error.getvalue())
