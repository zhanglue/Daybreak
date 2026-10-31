"""Server-local suppression leaves application logging intact."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import logging
import unittest

import uvicorn

from logger import Logger
from mcp_server import suppress_server_dependency_logs


class McpLoggingTests(unittest.TestCase):
    def test_dependency_logs_stay_silent_after_uvicorn_setup(self):
        names = ['fastmcp', 'fastmcp.server.mixins.transport', 'uvicorn',
                 'uvicorn.error', 'uvicorn.access', 'fastmcp_later_neighbor']
        for name in names:
            logging.getLogger(name)
        snapshots = {name: (value.disabled, value.propagate, value.level, value.handlers[:])
                     for name,value in logging.Logger.manager.loggerDict.items()
                     if isinstance(value, logging.Logger)}
        stdout, stderr, application = StringIO(), StringIO(), StringIO()
        Logger.close()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                suppress_server_dependency_logs()
                uvicorn.Config('synthetic:app', log_config=None, access_log=False)
                for name in names[:-1]:
                    logging.getLogger(name).critical('synthetic dependency output')
                # A child created after startup must not reach lastResort/root output.
                logging.getLogger('fastmcp.synthetic_late_child').error('synthetic late output')
                backend = Logger()._logger
                handler = logging.StreamHandler(application)
                backend.addHandler(handler)
                backend.setLevel(logging.INFO)
                Logger.INFO('synthetic Daybreak output')
                self.assertFalse(backend.disabled)
                self.assertEqual(application.getvalue().strip(), 'synthetic Daybreak output')
            self.assertNotIn('synthetic dependency output', stdout.getvalue() + stderr.getvalue())
            self.assertNotIn('synthetic late output', stdout.getvalue() + stderr.getvalue())
            self.assertEqual(stdout.getvalue(), '')
            self.assertFalse(logging.getLogger('fastmcp_later_neighbor').disabled)
        finally:
            Logger.close()
            for name, (disabled, propagate, level, handlers) in snapshots.items():
                target = logging.getLogger(name)
                target.disabled, target.propagate = disabled, propagate
                target.setLevel(level)
                target.handlers = handlers
            logging.Logger.manager.loggerDict.pop('fastmcp.synthetic_late_child', None)


class McpRequestLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_and_discovery_logs_are_safe_and_preserve_outcomes(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import AsyncMock, patch
        from fastmcp import Client
        from garmin_data_store import GarminDataStore
        from global_config import MCPServerConfig
        from mcp_server import create_server

        with TemporaryDirectory() as directory:
            config = MCPServerConfig()
            remote = AsyncMock()
            remote.get_daily_sleep.return_value = {'private_health_marker': 'private-result'}
            store = GarminDataStore(Path(directory).resolve() / 'data', config,
                                    client_factory=AsyncMock(return_value=remote))
            with patch('mcp_server.Logger.INFO') as info:
                async with Client(create_server(config, store=store)) as client:
                    await client.list_tools()
                    result = await client.call_tool('get_daily_sleep', {'calendar_date':'2026-10-01'})
                    self.assertEqual(result.data['status'], 'ok')
                    await client.call_tool('get_daily_sleep', {
                        'calendar_date':'2026-10-02', 'cache_mode':'local_only'})
                    bad = await client.call_tool('get_activity', {'activity_id':-1}, raise_on_error=False)
                    self.assertTrue(bad.is_error)
                    await client.list_resource_templates()
                lines = [call.args[0] % call.args[1:] for call in info.call_args_list]
            text = '\n'.join(lines)
            self.assertIn('method=tools/list', text)
            self.assertIn('method=resources/templates/list', text)
            self.assertIn('tool=get_daily_sleep; status=ok;', text)
            self.assertIn('tool=get_daily_sleep; status=error;', text)
            self.assertIn('tool=get_activity; status=error;', text)
            self.assertIn('elapsed_ms=', text)
            for private in ['2026-10-01', '2026-10-02', 'private-result', 'private_health_marker', str(directory)]:
                self.assertNotIn(private, text)
            received = [line.split('call_id=')[1].split(';')[0] for line in lines if 'request received' in line]
            finished = [line.split('call_id=')[1].split(';')[0] for line in lines if 'request finished' in line]
            self.assertCountEqual(received, finished)

    async def test_partial_and_cancelled_calls_keep_status_without_payload_logging(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from fastmcp.tools import ToolResult
        from mcp_server import MCPRequestLoggingMiddleware

        middleware = MCPRequestLoggingMiddleware()
        context = SimpleNamespace(message=SimpleNamespace(name='private-unknown-name', uri='private-resource-uri'))
        with patch('mcp_server.Logger.INFO') as info:
            result = await middleware.on_call_tool(context, AsyncMock(return_value=ToolResult(
                structured_content={'status':'partial', 'data':'private-content'})))
            self.assertEqual(result.structured_content['status'], 'partial')
            with self.assertRaises(asyncio.CancelledError):
                await middleware.on_read_resource(context, AsyncMock(side_effect=asyncio.CancelledError()))
        text = '\n'.join(call.args[0] % call.args[1:] for call in info.call_args_list)
        self.assertIn('tool=unknown; status=partial;', text)
        self.assertIn('method=resources/read; tool=-; status=cancelled;', text)
        self.assertNotIn('private-', text)
