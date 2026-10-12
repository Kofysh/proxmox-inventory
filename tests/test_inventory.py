import io
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError, URLError
import proxmox_inventory as app

ENV = {"PVE_URL": "https://pve.example.net:8006", "PVE_TOKEN_ID": "inventory@pve!test",
       "PVE_TOKEN_SECRET": "secret-only-for-tests"}
FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "examples/demo_api.json").read_text(encoding='utf-8'))

class InventoryTests(unittest.TestCase):
    def report(self):
        return app.build_report(FIXTURE['nodes'], FIXTURE['resources'], 'demo', 'fictif')

    def fake_client(self, raw):
        client = app.ProxmoxClient(ENV)
        client.opener = Mock()
        client.opener.open.return_value.__enter__ = Mock(return_value=io.BytesIO(raw))
        client.opener.open.return_value.__exit__ = Mock(return_value=False)
        return client

    def test_summary_excludes_templates(self):
        self.assertEqual(self.report()['summary'], dict(nodes=1, guests=3, running=2, stopped=1, other_states=0, templates=1))

    def test_missing_metrics_are_unknown(self):
        report = app.build_report([], [dict(vmid=42, type='qemu', node='pve')], 'demo', 'fictif')
        self.assertIsNone(report['guests'][0]['memory_allocated_bytes'])
        self.assertEqual(report['summary']['other_states'], 1)
        self.assertTrue(report['warnings'])

    def test_invalid_data_rejected(self):
        for change in [dict(maxmem=-1), dict(maxcpu=float('nan')), dict(vmid=None),
                       dict(maxdisk='abc'), dict(type='storage'), dict(node=123)]:
            with self.subTest(change=change), self.assertRaises(app.InventoryError):
                app.build_report([], [dict(FIXTURE['resources'][0], **change)], 'demo', 'fictif')

    def test_offline_node_flagged(self):
        report = app.build_report([dict(node='pve', status='offline')], [], 'live', 'test')
        self.assertIn('offline', report['warnings'][0])

    def test_invalid_config_rejected(self):
        cases = [{}, dict(ENV, PVE_URL='http://pve.example.net'),
                 dict(ENV, PVE_URL='https://user:password@pve.example.net'),
                 dict(ENV, PVE_URL='https://pve.example.net/api2/json'),
                 dict(ENV, PVE_TIMEOUT='nan'), dict(ENV, PVE_TIMEOUT='0'),
                 dict(ENV, PVE_TOKEN_ID='root'), dict(ENV, PVE_TOKEN_SECRET='secret\r\nx: y')]
        for env in cases:
            with self.assertRaises(app.InventoryError):
                app.ProxmoxClient(env)

    def test_tls_and_redirects(self):
        client = app.ProxmoxClient(ENV)
        handler = next(h for h in client.opener.handlers if isinstance(h, app.HTTPSHandler))
        self.assertTrue(handler._context.check_hostname)
        self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIsNone(app.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test'))

    def test_get_auth_and_route_allowlist(self):
        client = self.fake_client(b'{"data": []}')
        self.assertEqual(client.get('/nodes'), [])
        req = client.opener.open.call_args.args[0]
        self.assertEqual(req.get_method(), 'GET')
        self.assertEqual(req.full_url, 'https://pve.example.net:8006/api2/json/nodes')
        self.assertEqual(req.get_header('Authorization'), 'PVEAPIToken=inventory@pve!test=secret-only-for-tests')
        with self.assertRaises(app.InventoryError):
            client.get('/nodes/pve/qemu/100/status/start')
        self.assertEqual(client.opener.open.call_count, 1)

    def test_http_errors_hide_secret(self):
        for status, expected in [(401, 'authentification'), (403, 'droits'), (302, 'Redirection'), (500, 'HTTP 500')]:
            client = self.fake_client(b'')
            client.opener.open.side_effect = HTTPError('test', status, ENV['PVE_TOKEN_SECRET'], {}, None)
            with self.assertRaises(app.InventoryError) as caught:
                client.get('/nodes')
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn(ENV['PVE_TOKEN_SECRET'], str(caught.exception))

    def test_network_errors_sanitized(self):
        for error in [URLError('private detail'), TimeoutError(), ssl.SSLError('private detail')]:
            client = self.fake_client(b'')
            client.opener.open.side_effect = error
            with self.assertRaisesRegex(app.InventoryError, 'Connexion impossible') as caught:
                client.get('/nodes')
            self.assertNotIn('private detail', str(caught.exception))

    def test_malformed_response_rejected(self):
        for raw in [b'<html>error</html>', b'{"data": {}}', b'[]', b'\xff']:
            with self.assertRaises(app.InventoryError):
                self.fake_client(raw).get('/nodes')

    def test_large_response_rejected(self):
        client = self.fake_client(b'123456789')
        with patch.object(app, 'MAX_RESPONSE_BYTES', 8), self.assertRaises(app.InventoryError):
            client.get('/nodes')

    def test_demo_no_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'ProxmoxClient') as client:
            output = Path(directory) / 'report.json'
            with patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(app.main(['--demo', '--output', str(output)]), 0)
            client.assert_not_called()
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['mode'], 'demo')
            self.assertNotIn('secret', output.read_text(encoding='utf-8'))

    def test_failed_collection_preserves_old_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'ProxmoxClient') as client:
            output = Path(directory) / 'report.json'
            output.write_text('previous report')
            client.return_value.get.side_effect = [FIXTURE['nodes'], app.InventoryError('échec')]
            with patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(app.main(['--output', str(output)]), 1)
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous report')

    def test_output_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(app.InventoryError):
                app.write_report(self.report(), directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_terminal_escapes_removed(self):
        self.assertEqual(app.safe('vm\x1b[31m\n'), 'vm?[31m?')

if __name__ == '__main__':
    unittest.main()
