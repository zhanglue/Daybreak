"""Standalone entry-point checks with synthetic credentials and remote results."""

import asyncio
import io
from contextlib import redirect_stdout
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from garmin_connect_client import main
from global_config import GarminConnectClientConfig


class GarminMainTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_masks_inline_key_prints_results_and_closes(self):
        config = MagicMock()
        config.GarminConnectClient = GarminConnectClientConfig(api_key_string="synthetic-private-key")
        client = AsyncMock()
        client._token_expires_at = 1900000000
        client._token = "synthetic-private-token"
        client.get_heart_rate_zones.return_value = {"synthetic_zones": [100, 120]}
        client.get_user_profile_settings.return_value = {"synthetic_setting": True}
        output = io.StringIO()
        with patch("garmin_connect_client.GlobalConfig", return_value=config), patch(
            "garmin_connect_client.GarminConnectClient.get_client", return_value=client
        ), patch("garmin_connect_client.Logger"), redirect_stdout(output):
            self.assertEqual(await main([]), 0)
        text = output.getvalue()
        self.assertIn('"api_key_string": "********"', text)
        self.assertNotIn("synthetic-private-key", text)
        self.assertNotIn("synthetic-private-token", text)
        self.assertIn("synthetic_zones", text)
        self.assertIn("synthetic_setting", text)
        config.update_from_cli.assert_called_once_with([])
        client.aclose.assert_awaited_once()

    async def test_initialization_failure_has_safe_log_and_nonzero_exit(self):
        config = MagicMock()
        config.GarminConnectClient = GarminConnectClientConfig()
        with patch("garmin_connect_client.GlobalConfig", return_value=config), patch(
            "garmin_connect_client.GarminConnectClient.get_client", side_effect=ValueError("sensitive-detail")
        ), patch("garmin_connect_client.Logger") as logger, redirect_stdout(io.StringIO()):
            self.assertEqual(await main([]), 1)
            logger.ERROR.assert_called_once_with("Garmin standalone smoke test failed.")
            logger.close.assert_called_once()

    async def test_remote_failure_has_nonzero_exit_and_still_closes(self):
        config = MagicMock()
        config.GarminConnectClient = GarminConnectClientConfig()
        client = AsyncMock()
        client._token_expires_at = 1900000000
        client.get_heart_rate_zones.return_value = None
        client.get_user_profile_settings.return_value = {}
        with patch("garmin_connect_client.GlobalConfig", return_value=config), patch(
            "garmin_connect_client.GarminConnectClient.get_client", return_value=client
        ), patch("garmin_connect_client.Logger"), redirect_stdout(io.StringIO()):
            self.assertEqual(await main([]), 1)
            client.aclose.assert_awaited_once()

    async def test_full_main_flow_with_real_wrapper_and_mock_http(self):
        import base64
        import json
        from time import time
        import httpx
        from garmin_connect_client import GarminConnectClient

        payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time()) + 3600}).encode()).decode().rstrip("=")
        token = f"synthetic.{payload}.signature"
        observed = []
        real_async_client = httpx.AsyncClient

        def respond(request):
            observed.append(request)
            if request.method == "POST":
                self.assertEqual(request.headers["Authorization"], "ApiKey synthetic-private-key")
                return httpx.Response(200, text=token)
            self.assertEqual(request.headers["Authorization"], f"Bearer {token}")
            return httpx.Response(200, json={"synthetic": True})

        def create_transport(**kwargs):
            return real_async_client(**kwargs, transport=httpx.MockTransport(respond), trust_env=False)

        output = io.StringIO()
        with patch.object(GarminConnectClient, "_instance", None), patch.object(
            GarminConnectClient, "_instance_lock", asyncio.Lock()
        ), patch.object(GarminConnectClient, "_load_api_key", return_value="synthetic-private-key"), patch(
            "async_http_client.httpx.AsyncClient", side_effect=create_transport
        ), redirect_stdout(output):
            self.assertEqual(await main([]), 0)
            self.assertIsNone(GarminConnectClient._instance)
        self.assertEqual([request.method for request in observed], ["POST", "GET", "GET"])
        self.assertNotIn("synthetic-private-key", output.getvalue())
        self.assertNotIn(token, output.getvalue())
