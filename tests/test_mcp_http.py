"""Loopback-only HTTP checks using synthetic data and independent MCP clients."""

import asyncio
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastmcp import Client
import uvicorn

from garmin_data_store import GarminDataStore
from global_config import MCPServerConfig
from mcp_server import create_server, main


class McpHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_processes_share_service_and_survive_disconnect(self):
        with TemporaryDirectory() as directory:
            config = MCPServerConfig(data_directory=str(Path(directory).resolve() / 'data'))
            remote = AsyncMock()

            async def sleep_data(**parameters):
                await asyncio.sleep(0.05)
                return {'synthetic_score': 80}

            remote.get_daily_sleep.side_effect = sleep_data
            factory = AsyncMock(return_value=remote)
            store = GarminDataStore(config.data_directory, config, client_factory=factory)
            mcp = create_server(config, store=store)
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            app = mcp.http_app(path='/custom-mcp', host_origin_protection=True,
                               allowed_hosts=['127.0.0.1'], stateless_http=False)
            http = uvicorn.Server(uvicorn.Config(app, log_level='critical', lifespan='on', access_log=False))
            task = asyncio.create_task(http.serve(sockets=[listener]))
            process = None
            try:
                async with asyncio.timeout(10):
                    while not http.started:
                        if task.done():
                            await task
                            self.fail('HTTP server stopped before startup.')
                        await asyncio.sleep(0.01)
                url = f'http://127.0.0.1:{port}/custom-mcp'
                script = '''import asyncio, json, sys
from fastmcp import Client
async def run():
    async with Client(sys.argv[1]) as client:
        result = await client.call_tool('get_garmin_data', {
            'dataset': 'sleep', 'start_date': '2026-10-01'})
        print(json.dumps(result.data))
asyncio.run(run())
'''
                async with Client(url) as first:
                    self.assertEqual(len(await first.list_tools()), 32)
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, '-c', script, url,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    local_call = asyncio.create_task(first.call_tool('get_garmin_data', {
                        'dataset': 'sleep', 'start_date': '2026-10-01'}))
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
                    self.assertEqual(process.returncode, 0, stderr.decode())
                    self.assertEqual(json.loads(stdout)['status'], 'ok')
                    self.assertEqual((await local_call).data['status'], 'ok')
                    self.assertEqual(len(await first.list_tools()), 32)
                    remote.aclose.assert_not_awaited()
                remote.aclose.assert_not_awaited()
                async with Client(url) as second:
                    result = await second.call_tool('get_garmin_data', {
                        'dataset': 'sleep', 'start_date': '2026-10-01', 'cache_mode': 'local_only'})
                    self.assertEqual(result.data['records'][0]['source'], 'local')
                remote.get_daily_sleep.assert_awaited_once()
            finally:
                if process is not None and process.returncode is None:
                    process.kill()
                    await process.wait()
                http.should_exit = True
                await asyncio.wait_for(task, timeout=10)
                listener.close()
            remote.aclose.assert_awaited_once()

    async def test_entrypoint_uses_configured_http_listener(self):
        settings = MCPServerConfig(port=8123, path='/daybreak')
        config = Mock(MCPServer=settings)
        config.to_display_dict.return_value = {'MCPServer': {'port': 8123}}
        with patch('mcp_server.GlobalConfig', return_value=config), \
                patch('mcp_server.create_server') as create, patch('mcp_server.Logger'), \
                patch('mcp_server.suppress_server_dependency_logs') as suppress:
            main()
        suppress.assert_called_once_with()
        config.update_from_cli.assert_called_once_with()
        create.return_value.run.assert_called_once_with(
            transport='http', host='127.0.0.1', port=8123, path='/daybreak',
            stateless_http=False, host_origin_protection=True, show_banner=False,
            uvicorn_config={'log_config': None, 'access_log': False})
