import copy
import io
import json
from http.client import IncompleteRead
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
import proxmox_inventory as app
from test_inventory import ENV, FIXTURE
import test_inventory


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.before = app.build_report(FIXTURE['nodes'], FIXTURE['resources'], 'demo', 'fictif')
        self.after = copy.deepcopy(self.before)

    def test_identical_reports_and_live_memory_are_ignored(self):
        self.after['generated_at'] = '2099-01-01T00:00:00+00:00'
        self.after['nodes'][0]['memory_used_bytes'] += 1000
        self.assertFalse(app.compare_inventories(self.before, self.after)['has_changes'])

    def test_add_remove_and_modify(self):
        self.after['guests'].pop(1)
        added = copy.deepcopy(self.after['guests'][0])
        added['vmid'] = 300
        self.after['guests'].append(added)
        self.after['guests'][0]['status'] = 'stopped'
        self.after['guests'][0]['memory_allocated_bytes'] *= 2
        result = app.compare_inventories(self.before, self.after)['guests']
        self.assertEqual([r['vmid'] for r in result['added']], [300])
        self.assertEqual([r['vmid'] for r in result['removed']], [102])
        self.assertEqual(set(result['changed'][0]['changes']), {'status', 'memory_allocated_bytes'})

    def test_migration_is_modification_not_addition(self):
        self.after['guests'][0]['node'] = 'pve-lab-02'
        delta = app.compare_inventories(self.before, self.after)['guests']
        self.assertEqual(delta['added'], [])
        self.assertEqual(delta['removed'], [])
        self.assertEqual(delta['changed'][0]['changes']['node']['after'], 'pve-lab-02')

    def test_node_changes(self):
        self.after['nodes'][0]['status'] = 'offline'
        self.after['nodes'].append(dict(self.after['nodes'][0], name='pve-lab-02'))
        delta = app.compare_inventories(self.before, self.after)['nodes']
        self.assertEqual(len(delta['added']), 1)
        self.assertEqual(delta['changed'][0]['changes']['status']['before'], 'online')

    def test_rejects_incompatible_source_mode_scope_and_order(self):
        for changes in [dict(source='another cluster'), dict(mode='live'), dict(scope='partial'),
                        dict(generated_at='2000-01-01T00:00:00+00:00'), dict(generated_at='bad'),
                        dict(generated_at='2026-01-01T00:00:00'), dict(filters={'node':'pve'}),
                        dict(schema_version=2), dict(collection_status='failed')]:
            with self.subTest(changes=changes), self.assertRaises(app.InventoryError):
                app.compare_inventories(self.before, dict(self.after, **changes))

    def test_rejects_duplicate_or_malformed_resources(self):
        self.after['guests'].append(copy.deepcopy(self.after['guests'][0]))
        with self.assertRaises(app.InventoryError):
            app.compare_inventories(self.before, self.after)
        self.after = copy.deepcopy(self.before)
        self.after['guests'][0]['vcpu'] = 'two'
        with self.assertRaises(app.InventoryError):
            app.compare_inventories(self.before, self.after)

    def test_accepts_missing_optional_metrics(self):
        self.after['guests'][0]['memory_allocated_bytes'] = None
        result = app.compare_inventories(self.before, self.after)
        self.assertIsNone(result['guests']['changed'][0]['changes']['memory_allocated_bytes']['after'])

    def test_compare_cli_offline_and_protects_input(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'ProxmoxClient') as client:
            before, after, output = [Path(tmp)/name for name in ['before.json','after.json','diff.json']]
            app.write_report(self.before, before)
            app.write_report(self.after, after)
            with patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(app.main(['--compare',str(before),str(after),'--output',str(output)]),0)
            client.assert_not_called()
            self.assertFalse(json.loads(output.read_text(encoding='utf-8'))['has_changes'])
            original = before.read_bytes()
            with patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(app.main(['--compare',str(before),str(after),'--output',str(before)]),1)
            self.assertEqual(before.read_bytes(),original)

    def test_filter_changes_display_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.stdout', new_callable=io.StringIO) as stdout:
            output=Path(tmp)/'inventory.json'
            self.assertEqual(app.main(['--demo','--node','pve-lab-01','--status','running','--output',str(output)]),0)
            self.assertIn('vps-demo-01', stdout.getvalue())
            self.assertNotIn('vps-demo-02', stdout.getvalue())
            self.assertEqual(len(json.loads(output.read_text(encoding='utf-8'))['guests']),4)

    def test_empty_filter_is_explicit(self):
        with patch('sys.stdout', new_callable=io.StringIO) as stdout:
            app.print_summary(self.before, node='missing')
        self.assertIn('Aucune ressource',stdout.getvalue())

    def test_invalid_combinations_fail_before_network(self):
        with patch.object(app,'ProxmoxClient') as client, patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as caught:
                app.main(['--compare','a','b','--demo'])
            self.assertEqual(caught.exception.code,2)
            client.assert_not_called()

    def test_invalid_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json'
            for content in [b'not json',b'[]',b'\xff',b'{"schema_version":1}']:
                path.write_bytes(content)
                with self.assertRaises(app.InventoryError):
                    app.read_inventory(path)
            with patch.object(app,'MAX_RESPONSE_BYTES',3), self.assertRaises(app.InventoryError):
                app.read_inventory(path)

    def test_truncated_http_response_is_handled(self):
        client=test_inventory.InventoryTests().fake_client(b'')
        client.opener.open.side_effect=IncompleteRead(b'partial')
        with self.assertRaisesRegex(app.InventoryError,'Connexion impossible'):
            client.get('/nodes')

    def test_custom_ca_is_loaded(self):
        context=ssl.create_default_context()
        with patch.object(app.ssl,'create_default_context',return_value=context) as factory:
            app.ProxmoxClient(dict(ENV,PVE_CA_FILE='/trusted/ca.pem'))
            factory.assert_called_once_with(cafile='/trusted/ca.pem')

    def test_bad_ca_is_handled(self):
        with patch.object(app.ssl,'create_default_context',side_effect=ssl.SSLError('bad pem')):
            with self.assertRaisesRegex(app.InventoryError,'PVE_CA_FILE'):
                app.ProxmoxClient(dict(ENV,PVE_CA_FILE='bad.pem'))
