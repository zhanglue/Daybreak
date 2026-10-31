"""Synthetic Garmin credential resolution checks without real credentials."""

import asyncio
import base64
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from garmin_connect_client import GarminConnectClient, token_check
from global_config import GarminConnectClientConfig


class GarminConnectClientTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(GarminConnectClient)
        self.error_patch = patch("garmin_connect_client.Logger.ERROR")
        self.error_log = self.error_patch.start()
        self.addCleanup(self.error_patch.stop)

    def test_inline_key_precedes_file(self):
        self.client._config = GarminConnectClientConfig(
            api_key_string=" synthetic-key ", api_key_file="unused.txt"
        )
        with patch.object(Path, "read_text") as read:
            self.assertEqual(self.client._load_api_key(), "synthetic-key")
            read.assert_not_called()

    def test_file_fallback_uses_repository_root(self):
        self.client._config = GarminConnectClientConfig(
            api_key_string=" ", api_key_file="synthetic-key.txt"
        )
        paths = []

        def read(path, *, encoding):
            paths.append(path)
            self.assertEqual(encoding, "utf-8")
            return " synthetic-file-key\n"

        with patch.object(Path, "read_text", read):
            self.assertEqual(self.client._load_api_key(), "synthetic-file-key")
        self.assertEqual(paths, [Path(__file__).resolve().parents[1] / "synthetic-key.txt"])

    def test_missing_empty_and_unreadable_keys(self):
        self.client._config = GarminConnectClientConfig(api_key_file="")
        with self.assertRaises(ValueError):
            self.client._load_api_key()
        self.error_log.assert_called_once_with("Garmin API key is not configured.")
        self.error_log.reset_mock()
        self.client._config = GarminConnectClientConfig(api_key_file="synthetic-key.txt")
        with patch.object(Path, "read_text", return_value=" \n"):
            with self.assertRaises(ValueError):
                self.client._load_api_key()
        self.error_log.assert_called_once_with("Garmin API key file is empty.")
        self.error_log.reset_mock()
        with patch.object(Path, "read_text", side_effect=OSError("sensitive details")):
            with self.assertRaises(ValueError) as caught:
                self.client._load_api_key()
        self.assertNotIn("sensitive details", str(caught.exception))
        self.error_log.assert_called_once_with("Garmin API key file could not be read.")

    def test_path_escaping_repository_is_rejected(self):
        self.client._config = GarminConnectClientConfig(api_key_file="../synthetic-key.txt")
        with patch.object(Path, "read_text") as read:
            with self.assertRaises(ValueError):
                self.client._load_api_key()
            read.assert_not_called()
        self.error_log.assert_called_once_with(
            "Garmin API key file must resolve inside the repository."
        )


class GarminConnectClientFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved_instance = GarminConnectClient._instance
        self.saved_lock = GarminConnectClient._instance_lock
        GarminConnectClient._instance = None
        GarminConnectClient._instance_lock = asyncio.Lock()

    async def asyncTearDown(self):
        GarminConnectClient._instance = self.saved_instance
        GarminConnectClient._instance_lock = self.saved_lock

    async def test_concurrent_calls_publish_only_after_initialization(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def initialize():
            started.set()
            await release.wait()

        with patch.object(GarminConnectClient, "_initialize", side_effect=initialize) as init:
            tasks = [asyncio.create_task(GarminConnectClient.get_client()) for _ in range(16)]
            await started.wait()
            self.assertIsNone(GarminConnectClient._instance)
            release.set()
            clients = await asyncio.gather(*tasks)
            self.assertTrue(all(client is clients[0] for client in clients))
            self.assertIs(await GarminConnectClient.get_client(), clients[0])
            init.assert_awaited_once()

    async def test_failed_or_cancelled_initialization_can_retry(self):
        for error in (ValueError("synthetic failure"), asyncio.CancelledError()):
            GarminConnectClient._instance = None
            with patch.object(GarminConnectClient, "_initialize", new_callable=AsyncMock) as init:
                init.side_effect = error
                with self.assertRaises(type(error)):
                    await GarminConnectClient.get_client()
                self.assertIsNone(GarminConnectClient._instance)
                init.side_effect = None
                client = await GarminConnectClient.get_client()
                self.assertIs(client, GarminConnectClient._instance)

    async def test_factory_obtains_token_before_returning(self):
        with patch("garmin_connect_client.AsyncHttpClient") as transport:
            transport.return_value.aclose = AsyncMock()
            with patch.object(GarminConnectClient, "_request_token", return_value=("synthetic-token", 5000)):
                client = await GarminConnectClient.get_client()
            self.assertEqual(client._token, "synthetic-token")
            self.assertEqual(client._token_expires_at, 5000)
            self.assertFalse(hasattr(client, "_api_key"))
            await client.aclose()
            transport.return_value.aclose.assert_awaited_once()
            self.assertIsNone(GarminConnectClient._instance)

    async def test_initial_token_failure_closes_transport(self):
        with patch("garmin_connect_client.AsyncHttpClient") as transport:
            transport.return_value.aclose = AsyncMock()
            with patch.object(GarminConnectClient, "_request_token", side_effect=ValueError("synthetic")):
                with self.assertRaises(ValueError):
                    await GarminConnectClient.get_client()
            transport.return_value.aclose.assert_awaited_once()
            self.assertIsNone(GarminConnectClient._instance)

    async def test_direct_construction_is_rejected_and_logged(self):
        with patch("garmin_connect_client.Logger.ERROR") as log:
            with self.assertRaises(TypeError) as caught:
                GarminConnectClient()
            log.assert_called_once_with(str(caught.exception))


class GarminConnectClientTokenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = object.__new__(GarminConnectClient)
        self.client._token = "old-token"
        self.client._token_expires_at = 1600
        self.client._token_lock = asyncio.Lock()

    async def test_remote_calls_wait_for_one_refresh_and_use_new_token(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def refresh():
            started.set()
            await release.wait()
            return "new-token", 5000

        @token_check
        async def remote(client):
            return client._token

        with patch("garmin_connect_client.time", return_value=1000):
            with patch.object(self.client, "_request_token", side_effect=refresh) as request:
                tasks = [asyncio.create_task(remote(self.client)) for _ in range(16)]
                await started.wait()
                self.assertTrue(all(not task.done() for task in tasks))
                release.set()
                self.assertEqual(await asyncio.gather(*tasks), ["new-token"] * 16)
                request.assert_awaited_once()

    async def test_valid_token_does_not_refresh(self):
        self.client._token_expires_at = 1601
        with patch("garmin_connect_client.time", return_value=1000):
            with patch.object(self.client, "_request_token") as request:
                await self.client._ensure_token()
                request.assert_not_called()

    async def test_failed_refresh_blocks_remote_execution_and_allows_retry(self):
        remote = token_check(AsyncMock())
        with patch("garmin_connect_client.time", return_value=1000):
            with patch.object(self.client, "_request_token", side_effect=ValueError("synthetic")):
                with self.assertRaises(ValueError):
                    await remote(self.client)
            remote.__wrapped__.assert_not_awaited()
            self.assertEqual(self.client._token, "old-token")
            with patch.object(self.client, "_request_token", return_value=("new-token", 5000)):
                await self.client._ensure_token()
        self.assertEqual(self.client._token, "new-token")

    async def test_request_uses_local_key_and_jwt_expiration(self):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": 5000}).encode()).decode().rstrip("=")
        token = f"header.{payload}.signature"
        transport = AsyncMock()
        transport.post.return_value.text = token + "\n"
        self.client._http_client = transport
        with patch.object(self.client, "_load_api_key", return_value="synthetic-key"):
            with patch("garmin_connect_client.time", return_value=1000):
                self.assertEqual(await self.client._request_token(), (token, 5000))
        transport.post.assert_awaited_once_with(
            "/personalapitoken-service/personal-api/personal-api-key/token",
            headers={"Authorization": "ApiKey synthetic-key", "Accept": "*/*"},
        )
        self.assertFalse(hasattr(self.client, "_api_key"))

    async def test_invalid_token_responses_are_logged_without_contents(self):
        transport = AsyncMock()
        self.client._http_client = transport
        payloads = [{}, [], {"exp": True}, {"exp": "5000"}, {"exp": 1000}, {"exp": 1600}, {"exp": float("inf")}]
        tokens = ["sensitive-invalid-token"] + [
            "header." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + ".signature"
            for payload in payloads
        ]
        with patch.object(self.client, "_load_api_key", return_value="synthetic-key"):
            with patch("garmin_connect_client.time", return_value=1000):
                for token in tokens:
                    transport.post.return_value.text = token
                    with self.subTest(token=token), patch("garmin_connect_client.Logger.ERROR") as log:
                        with self.assertRaises(ValueError) as caught:
                            await self.client._request_token()
                        log.assert_called_once_with(str(caught.exception))
                        self.assertNotIn(token, str(caught.exception))
