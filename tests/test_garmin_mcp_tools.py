"""All-endpoint MCP schema, parameter forwarding, and binary-resource checks."""

import asyncio
import base64
from datetime import datetime, timezone
from io import BytesIO
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from fastmcp import Client

from garmin_connect_client import GarminConnectClient
from garmin_data_store import GarminDataStore
from garmin_mcp_tools import API_TOOLS
from global_config import MCPServerConfig
from mcp_server import create_server


def synthetic_zip(payload=b'synthetic-fit-content'):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('synthetic.fit', payload)
    return buffer.getvalue()


class GarminMcpToolsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'store'
        self.config = MCPServerConfig(data_directory=str(self.root))
        self.remote = AsyncMock()
        for name in API_TOOLS:
            getattr(self.remote, name).return_value = {'endpoint': name}
        self.zip = synthetic_zip()
        self.remote.download_activity.return_value = self.zip
        self.factory = AsyncMock(return_value=self.remote)
        self.now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        self.store = GarminDataStore(self.root, self.config, client_factory=self.factory, clock=lambda: self.now)
        self.server = create_server(self.config, store=self.store)

    async def asyncTearDown(self):
        await self.store.aclose()
        self.temp.cleanup()

    async def test_discovery_matches_inventory_and_every_client_parameter(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/garmin_openapi_parameters.json').read_text())
        expected = {endpoint['method'] for endpoint in fixture['endpoints']}
        self.assertEqual(set(API_TOOLS), expected)
        self.assertEqual(len(expected), 26)
        async with Client(self.server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            self.assertEqual(len(tools), 32)
            self.assertNotIn('get_client', tools)
            self.assertNotIn('aclose', tools)
            for name in expected:
                with self.subTest(endpoint=name):
                    signature = inspect.signature(getattr(GarminConnectClient, name))
                    params = {key: p for key,p in signature.parameters.items() if key != 'self'}
                    schema = tools[name].input_schema
                    self.assertEqual(set(schema['properties']), set(params) | {'cache_mode'})
                    required = {key for key,p in params.items() if p.default is inspect.Parameter.empty}
                    self.assertEqual(set(schema.get('required', [])), required)
                    for key,p in params.items():
                        if p.default is not inspect.Parameter.empty:
                            self.assertEqual(schema['properties'][key]['default'], p.default)
            self.factory.assert_not_awaited()

    async def test_all_26_endpoints_forward_every_parameter_and_reuse_local_records(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/garmin_openapi_parameters.json').read_text())
        async with Client(self.server) as client:
            for endpoint in fixture['endpoints']:
                name = endpoint['method']
                args = {}
                for param in endpoint['parameters']:
                    key, schema = param['python_name'], param['schema']
                    if key in ('calendar_date', 'start_date', 'today_date'):
                        value = '2026-10-01'
                    elif key == 'end_date':
                        value = '2026-10-02'
                    elif key == 'sort_order':
                        value = 'asc'
                    elif key == 'favorite':
                        value = 0
                    elif schema['type'] == 'boolean':
                        value = not schema.get('default', True)
                    elif schema['type'] == 'array':
                        value = ['synthetic-a', 'synthetic-b']
                    elif schema['type'] in ('number', 'integer'):
                        value = 5
                    else:
                        value = 'synthetic'
                    args[key] = value
                with self.subTest(endpoint=name):
                    result = (await client.call_tool(name, args)).data
                    self.assertEqual(result['status'], 'ok')
                    self.assertTrue(result['records'][0]['persisted'])
                    getattr(self.remote, name).assert_awaited_once_with(**args)
                    local = (await client.call_tool(name, {**args, 'cache_mode': 'local_only'})).data
                    self.assertEqual(local['records'][0]['source'], 'local')
                    getattr(self.remote, name).assert_awaited_once()

    async def test_optional_dates_preserve_remote_defaults_and_day_scoped_identity(self):
        async with Client(self.server) as client:
            for name in ['get_daily_sleep', 'get_daily_sleep_summaries', 'get_daily_summaries',
                         'get_daily_body_battery', 'search_activities']:
                result = (await client.call_tool(name, {})).data
                self.assertEqual(result['status'], 'ok')
                self.assertIn('cache_context', result['records'][0])
                kwargs = getattr(self.remote, name).call_args.kwargs
                if name == 'get_daily_sleep':
                    self.assertIsNone(kwargs['calendar_date'])
                else:
                    self.assertIsNone(kwargs['start_date'])
                    self.assertIsNone(kwargs['end_date'])

    async def test_binary_download_resource_integrity_stale_fallback_and_repair(self):
        async with Client(self.server) as client:
            result = (await client.call_tool('download_activity', {'activity_id': 123})).data
            record = result['records'][0]
            data = record['data']
            content = await client.read_resource(data['resource_uri'])
            self.assertEqual(base64.b64decode(content[0].blob), self.zip)
            self.assertEqual(data['size_bytes'], len(self.zip))
            self.assertNotIn(str(self.root), json.dumps(result))
            self.remote.download_activity.return_value = None
            failed = (await client.call_tool('download_activity', {'activity_id': 123, 'cache_mode': 'refresh'})).data
            self.assertEqual(failed['status'], 'partial')
            self.assertEqual(failed['records'][0]['data'], data)
            archive_path = next(self.root.glob('activities/123/*.zip'))
            archive_path.write_bytes(b'corrupt')
            missing = (await client.call_tool('download_activity', {'activity_id': 123, 'cache_mode': 'local_only'})).data
            self.assertEqual(missing['status'], 'error')
            self.remote.download_activity.return_value = self.zip
            repaired = (await client.call_tool('download_activity', {'activity_id': 123})).data
            self.assertEqual(repaired['records'][0]['source'], 'remote')
            self.assertEqual(archive_path.read_bytes(), self.zip)
            self.remote.download_activity.return_value = synthetic_zip(b'new-synthetic-fit')
            with patch.object(self.store, '_write', side_effect=OSError('synthetic-metadata-failure')):
                publication = (await client.call_tool('download_activity', {
                    'activity_id':123, 'cache_mode':'refresh'})).data
            self.assertFalse(publication['records'][0]['persisted'])
            self.assertIsNone(publication['records'][0]['data']['resource_uri'])
            previous = (await client.call_tool('download_activity', {
                'activity_id':123, 'cache_mode':'local_only'})).data
            self.assertEqual(previous['records'][0]['data'], data)
            original = await client.read_resource(data['resource_uri'])
            self.assertEqual(base64.b64decode(original[0].blob), self.zip)

    async def test_parameter_variants_validation_and_download_failures(self):
        async with Client(self.server) as client:
            for flag in [False, True]:
                await client.call_tool('get_weight_measurements', dict(
                    start_date='2026-10-01', end_date='2026-10-02', include_all=flag))
            self.assertEqual(self.remote.get_weight_measurements.await_count, 2)
            for name,args in [
                ('get_daily_food_logs', {'calendar_date':'2026-02-30'}),
                ('get_daily_hrv_summaries', {'start_date':'2026-10-02','end_date':'2026-10-01'}),
                ('get_daily_steps', {'start_date':'2026-10-01','end_date':'2026-10-29'}),
                ('get_activity', {'activity_id':'../file'}),
                ('search_activities', {'limit':100}),
                ('search_activities', {'unknown_filter':1}),
            ]:
                self.assertTrue((await client.call_tool(name,args,raise_on_error=False)).is_error)
            self.remote.download_activity.return_value = b'not-a-zip'
            result = (await client.call_tool('download_activity', {'activity_id': 321})).data
            self.assertEqual(result['status'], 'error')
            self.assertFalse(list(self.root.glob('activities/321/*')))
            self.remote.download_activity.return_value = self.zip
            with patch('garmin_data_store.os.replace', side_effect=OSError('synthetic-write-error')):
                failed = (await client.call_tool('download_activity', {'activity_id':321})).data
            self.assertFalse(failed['records'][0]['persisted'])
            self.assertIsNone(failed['records'][0]['data']['resource_uri'])
            with self.assertRaises(ValueError):
                self.store.read_archive('../file', 'a' * 64)

    async def test_concurrent_download_refreshes_share_one_fetch(self):
        async with Client(self.server) as client:
            await client.call_tool('download_activity', {'activity_id':123})
            self.remote.download_activity.reset_mock()
            entered = asyncio.Event()
            release = asyncio.Event()

            async def download(**parameters):
                entered.set()
                await release.wait()
                return self.zip

            self.remote.download_activity.side_effect = download
            args = {'activity_id':123, 'cache_mode':'refresh'}
            first = asyncio.create_task(client.call_tool('download_activity', args))
            await asyncio.wait_for(entered.wait(), timeout=5)
            second = asyncio.create_task(client.call_tool('download_activity', args))
            # Wait until the second store request is queued on the same lock.
            async with asyncio.timeout(5):
                while not any(lock._waiters for lock in self.store._locks.values()):
                    await asyncio.sleep(0)
            release.set()
            results = await asyncio.gather(first, second)
            self.assertTrue(all(result.data['status'] == 'ok' for result in results))
            self.remote.download_activity.assert_awaited_once_with(activity_id=123)
