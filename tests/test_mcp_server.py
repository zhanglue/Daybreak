"""Synthetic MCP integration and local persistence checks; never use account data."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from async_http_client import HttpTimeoutError
from garmin_data_store import GarminDataStore
from global_config import MCPServerConfig
from mcp_server import create_server


class McpServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name).resolve() / 'store'
        self.now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        self.remote = AsyncMock()
        self.remote.get_daily_sleep.return_value = {'sleepScore': 80}
        self.remote.get_daily_user_summary.return_value = {'steps': 123}
        self.remote.get_weight_measurements.return_value = {'measurements': []}
        self.remote.search_activities.return_value = [{'activityId': 12}]
        self.factory = AsyncMock(return_value=self.remote)
        self.store = GarminDataStore(self.root, MCPServerConfig(timezone_name='Asia/Shanghai'),
                                    client_factory=self.factory, clock=lambda: self.now)

    async def asyncTearDown(self):
        await self.store.aclose()
        self.directory.cleanup()

    async def test_mcp_discovery_roundtrip_and_local_only(self):
        server = create_server(MCPServerConfig(timezone_name='Asia/Shanghai'), store=self.store)
        async with Client(server) as client:
            names = {tool.name for tool in await client.list_tools()}
            self.assertEqual(len(names), 32)
            args = dict(dataset='sleep', start_date='2026-10-30')
            missing = (await client.call_tool('get_garmin_data', {**args, 'cache_mode': 'local_only'})).data
            self.assertEqual(missing['status'], 'error')
            self.factory.assert_not_awaited()
            fetched = (await client.call_tool('get_garmin_data', args)).data
            self.assertEqual(fetched['records'][0]['source'], 'remote')
            cached = (await client.call_tool('get_garmin_data', args)).data
            self.assertEqual(cached['records'][0]['source'], 'local')
            listed = (await client.call_tool('list_local_garmin_data', dict(
                start_date='2026-10-30', end_date='2026-10-30', datasets=['sleep']))).data
            self.assertNotIn('data', listed['records'][0])
            self.remote.get_daily_sleep.assert_awaited_once()
        self.remote.aclose.assert_awaited_once()

    async def test_daily_gaps_and_concurrent_local_misses(self):
        async with Client(create_server(MCPServerConfig(timezone_name='Asia/Shanghai'), store=self.store)) as client:
            args = dict(dataset='sleep', start_date='2026-10-01', end_date='2026-10-02')
            await asyncio.gather(*(client.call_tool('get_garmin_data', args) for _ in range(4)))
            self.assertEqual(self.remote.get_daily_sleep.await_count, 2)
            await client.call_tool('get_garmin_data', {**args, 'end_date': '2026-10-03'})
            self.assertEqual(self.remote.get_daily_sleep.await_count, 3)
            self.assertEqual(len(list(self.root.glob('*/*.json'))), 3)

    async def test_freshness_stale_fallback_and_none_not_persisted(self):
        params = dict(calendar_date='2026-10-30')
        day = self.now.date() - timedelta(days=1)
        await self.store.read('get_daily_sleep', params, '2026-10-30', dated_end=day)
        original = next(self.root.glob('*/*.json')).read_bytes()
        self.now += timedelta(hours=1)
        self.remote.get_daily_sleep.return_value = None
        result = await self.store.read('get_daily_sleep', params, '2026-10-30', dated_end=day)
        self.assertTrue(result['stale'])
        self.assertEqual(result['warning'], 'remote_unavailable')
        self.assertEqual(next(self.root.glob('*/*.json')).read_bytes(), original)
        failed = await self.store.read('get_daily_sleep', {'calendar_date': '2026-10-31'}, '2026-10-31')
        self.assertEqual(failed['status'], 'error')
        self.assertEqual(len(list(self.root.glob('*/*.json'))), 1)

    async def test_parameter_identity_corruption_and_atomic_failure(self):
        params = dict(start_date='2026-10-01', end_date='2026-10-02', include_all=False)
        await self.store.read('get_weight_measurements', params, 'ranges')
        path = next(self.root.glob('*/*.json'))
        original = path.read_bytes()
        with patch('garmin_data_store.os.replace', side_effect=OSError('synthetic')):
            result = await self.store.read('get_weight_measurements', params, 'ranges', mode='refresh')
        self.assertFalse(result['persisted'])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(list(path.parent.iterdir())), 1)
        await self.store.read('get_weight_measurements', {**params, 'include_all': True}, 'ranges')
        self.assertEqual(len(list(path.parent.iterdir())), 2)
        path.write_text('{broken', encoding='utf-8')
        local = await self.store.read('get_weight_measurements', params, 'ranges', mode='local_only')
        self.assertEqual(local['status'], 'error')

    async def test_symlink_rejection_and_cancelled_fetch(self):
        self.root.mkdir()
        (self.root / '2026-10-30').symlink_to(self.root.parent, target_is_directory=True)
        blocked = await self.store.read('get_daily_sleep', {}, '2026-10-30')
        self.assertEqual(blocked['error'], 'unsafe_local_path')
        self.factory.assert_not_awaited()
        self.remote.get_daily_sleep.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.store.read('get_daily_sleep', {}, '2026-10-29')
        self.assertFalse((self.root / '2026-10-29').exists())

    async def test_mcp_partial_results_validation_and_size_limit(self):
        self.remote.get_daily_sleep.return_value = None
        async with Client(create_server(MCPServerConfig(timezone_name='Asia/Shanghai'), store=self.store)) as client:
            result = (await client.call_tool('get_garmin_day', dict(
                calendar_date='2026-10-30', datasets=['summary', 'sleep']))).data
            self.assertEqual(result['status'], 'partial')
            for arguments in [dict(dataset='sleep', start_date='2026-10-01', end_date='2026-11-01'),
                              dict(dataset='unknown', start_date='2026-10-01')]:
                result = await client.call_tool('get_garmin_data', arguments, raise_on_error=False)
                self.assertTrue(result.is_error)
            self.remote.get_daily_sleep.return_value = {'samples': 'x' * (256 * 1024)}
            large = (await client.call_tool('get_garmin_data', dict(dataset='sleep', start_date='2026-10-29'))).data
            self.assertEqual(large['error'], 'result_too_large')
            persisted = list(self.root.glob('2026-10-29/*.json'))
            self.assertEqual(len(persisted), 1)
            self.assertGreater(len(json.loads(persisted[0].read_text())['data']['samples']), 1000)

    async def test_range_and_search_are_exact_request_cached(self):
        async with Client(create_server(MCPServerConfig(timezone_name='Asia/Shanghai'), store=self.store)) as client:
            args = dict(start_date='2026-10-01', end_date='2026-10-02')
            await client.call_tool('get_garmin_data', dict(dataset='weight', **args))
            await client.call_tool('get_garmin_data', dict(dataset='weight', **args))
            self.remote.get_weight_measurements.assert_awaited_once()
            await client.call_tool('search_garmin_activities', args)
            await client.call_tool('search_garmin_activities', {**args, 'start': 20})
            self.assertEqual(self.remote.search_activities.await_count, 2)

    async def test_stdio_entrypoint_discovery_without_data_access(self):
        script = Path(__file__).resolve().parents[1] / 'src/mcp_server.py'
        log_file = Path(self.directory.name) / 'startup.log'
        transport = PythonStdioTransport(script, args=[
            '--MCPServer.transport', 'stdio',
            '--MCPServer.timezone-name', 'Asia/Shanghai',
            '--GarminConnectClient.api-key-string', 'synthetic-startup-secret',
            '--Logging.level', 'INFO', '--Logging.console.enabled', '--Logging.console.level', 'INFO',
        ], cwd=self.directory.name, keep_alive=False, log_file=log_file)
        async with Client(transport) as client:
            self.assertEqual(len(await client.list_tools()), 32)
        logs = log_file.read_text(encoding='utf-8')
        self.assertIn('Effective configuration:', logs)
        self.assertNotIn("Starting MCP server 'Daybreak'", logs)
        self.assertNotIn('synthetic-startup-secret', logs)
        self.assertIn('"api_key_string": "********"', logs)
        self.assertIn('"timezone_name": "Asia/Shanghai"', logs)
        positions = [logs.index('"' + name + '":') for name in (
            'MCPServer', 'GarminConnectClient', 'GeneralHttpClient', 'Logging')]
        self.assertEqual(positions, sorted(positions))

    async def test_endpoint_limits_and_old_empty_refresh(self):
        async with Client(create_server(MCPServerConfig(timezone_name='Asia/Shanghai'), store=self.store)) as client:
            result = await client.call_tool('get_garmin_data', dict(
                dataset='steps', start_date='2026-10-01', end_date='2026-10-29'), raise_on_error=False)
            self.assertTrue(result.is_error)
            self.factory.assert_not_awaited()
        self.remote.get_daily_sleep.return_value = []
        params = dict(calendar_date='2026-10-01')
        day = self.now.date() - timedelta(days=30)
        await self.store.read('get_daily_sleep', params, '2026-10-01', dated_end=day)
        self.now += timedelta(hours=1)
        await self.store.read('get_daily_sleep', params, '2026-10-01', dated_end=day)
        self.assertEqual(self.remote.get_daily_sleep.await_count, 2)

    async def test_auth_transport_failure_and_offline_restart(self):
        self.factory.side_effect = HttpTimeoutError('synthetic')
        params = dict(calendar_date='2026-10-01')
        unavailable = await self.store.read('get_daily_sleep', params, '2026-10-01')
        self.assertEqual(unavailable['error'], 'remote_unavailable')
        self.factory.side_effect = None
        await self.store.read('get_daily_sleep', params, '2026-10-01')
        offline_factory = AsyncMock(side_effect=AssertionError('must not authenticate'))
        restarted = GarminDataStore(self.root, MCPServerConfig(timezone_name='Asia/Shanghai'),
                                    client_factory=offline_factory, clock=lambda: self.now)
        result = await restarted.read('get_daily_sleep', params, '2026-10-01',
                                      dated_end=self.now.date() - timedelta(days=30))
        self.assertEqual(result['source'], 'local')
        offline_factory.assert_not_awaited()

    async def test_configured_source_selection_and_unsupported_sources(self):
        config = MCPServerConfig(data_directory=str(self.root), timezone_name='Asia/Shanghai')
        with patch('mcp_server.GarminConnectClient.get_client', self.factory):
            server = create_server(config)
            self.factory.assert_not_awaited()
            async with Client(server) as client:
                await client.list_tools()
                self.factory.assert_not_awaited()
                await client.call_tool('get_garmin_data', dict(dataset='sleep', start_date='2026-10-01'))
            self.factory.assert_awaited_once()
            self.remote.aclose.assert_awaited_once()
        for source in ['other', '', 'GARMIN_CONNECT']:
            with self.subTest(source=source), patch('mcp_server.Logger.ERROR') as error:
                with self.assertRaises(NotImplementedError):
                    create_server(MCPServerConfig(data_source=source))
                error.assert_called_once_with('MCP data source is not implemented.')
