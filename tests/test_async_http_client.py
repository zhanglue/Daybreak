"""Verify the pool registry contract without network access."""

import asyncio
import unittest

import httpx
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

from async_http_client import (
    AsyncHttpClient, AsyncHttpClientsManager, AsyncHttpClientConfig,
    HttpResponse, HttpClientError, HttpStatusError, HttpTimeoutError,
    HttpConnectionError, HttpTransportError,
)


class AsyncHttpClientTests(unittest.TestCase):
    def setUp(self):
        error_log = patch("async_http_client.Logger.ERROR")
        self.error_log = error_log.start()
        self.addCleanup(error_log.stop)
        # Restore the application's singleton after each test.
        singleton = patch.object(AsyncHttpClientsManager, "_instance", None)
        singleton.start()
        self.addCleanup(singleton.stop)
        self.registry = AsyncHttpClientsManager
        self.addCleanup(lambda: asyncio.run(self.registry.aclose()))

    def test_construction_returns_same_instance(self):
        first = AsyncHttpClientsManager()
        self.assertIs(first, AsyncHttpClientsManager())
        self.assertEqual(first._pools, {})

    def test_concurrent_construction_returns_same_instance(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            instances = list(executor.map(lambda _: AsyncHttpClientsManager(), range(32)))
        self.assertTrue(all(instance is instances[0] for instance in instances))

    def test_class_methods_lazily_create_and_share_singleton(self):
        self.assertIsNone(AsyncHttpClientsManager._instance)
        AsyncHttpClientsManager.create_client(AsyncHttpClientConfig())
        instance = AsyncHttpClientsManager()
        self.assertIs(instance, AsyncHttpClientsManager._instance)
        self.assertIn("default", instance._pools)
        self.assertIs(AsyncHttpClientsManager.get_client(), instance._pools["default"])
        self.assertIs(instance, AsyncHttpClientsManager())
        with self.assertRaises(ValueError):
            instance.create_client(AsyncHttpClientConfig())

    def test_missing_pool_lookup_lazily_creates_singleton(self):
        self.assertIsNone(AsyncHttpClientsManager._instance)
        with self.assertRaises(RuntimeError):
            AsyncHttpClientsManager.get_client()
        self.assertIsInstance(AsyncHttpClientsManager._instance, AsyncHttpClientsManager)
        self.assertEqual(AsyncHttpClientsManager()._pools, {})

    def test_default_requires_explicit_build(self):
        with self.assertRaisesRegex(RuntimeError, "'default'.*not been built"):
            self.registry.get_client()
        self.registry.create_client(AsyncHttpClientConfig())
        self.assertIsInstance(self.registry.get_client(), AsyncHttpClient)

    def test_named_pools_do_not_implicitly_build_default(self):
        for name in ("first", "second"):
            self.registry.create_client(AsyncHttpClientConfig(name=name))
            self.assertIsInstance(self.registry.get_client(name), AsyncHttpClient)
        with self.assertRaises(RuntimeError):
            self.registry.get_client()

    def test_duplicate_build_is_rejected(self):
        config = AsyncHttpClientConfig()
        self.registry.create_client(config)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.registry.create_client(config)

    def test_concurrent_duplicate_build_has_one_winner(self):
        def build(_):
            try:
                self.registry.create_client(AsyncHttpClientConfig())
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(build, range(32)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(list(self.registry()._pools), ["default"])

    def test_lookup_does_not_wait_for_writer_or_singleton_lock(self):
        self.registry.create_client(AsyncHttpClientConfig())
        instance = self.registry()

        def lookup():
            self.assertIs(self.registry.get_client(), instance._pools["default"])
            with self.assertRaises(RuntimeError):
                self.registry.get_client("missing")

        with ThreadPoolExecutor(max_workers=1) as executor:
            with instance._pool_write_lock, self.registry._instance_lock:
                result = executor.submit(lookup)
                result.result(timeout=2)

    def test_failed_pool_construction_does_not_publish_pool(self):
        with patch("async_http_client.httpx.AsyncClient", side_effect=ValueError("failed")):
            with self.assertRaisesRegex(ValueError, "failed"):
                self.registry.create_client(AsyncHttpClientConfig())
        with self.assertRaises(RuntimeError):
            self.registry.get_client()
        self.registry.create_client(AsyncHttpClientConfig())

    def test_invalid_configuration_does_not_register_pool(self):
        with self.assertRaises(TypeError):
            self.registry.create_client({"name": "default"})
        for name in ("", "  ", None):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.registry.create_client(AsyncHttpClientConfig(name=name))
                with self.assertRaises(ValueError):
                    self.registry.get_client(name)
        with self.assertRaises(RuntimeError):
            self.registry.get_client()


class AsyncHttpClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        error_log = patch("async_http_client.Logger.ERROR")
        self.error_log = error_log.start()
        self.addCleanup(error_log.stop)
        singleton = patch.object(AsyncHttpClientsManager, "_instance", None)
        singleton.start()
        self.addCleanup(singleton.stop)
        self.addAsyncCleanup(AsyncHttpClientsManager.aclose)

    async def test_clients_are_distinct_by_name_and_reused_by_lookup(self):
        AsyncHttpClientsManager.create_client(AsyncHttpClientConfig())
        AsyncHttpClientsManager.create_client(AsyncHttpClientConfig(name="other"))
        first = AsyncHttpClientsManager.get_client()
        self.assertIs(first, AsyncHttpClientsManager.get_client())
        self.assertIsNot(first, AsyncHttpClientsManager.get_client("other"))
        self.assertFalse(first.is_closed)
        await AsyncHttpClientsManager.aclose()
        self.assertTrue(first.is_closed)
        with self.assertRaises(RuntimeError):
            AsyncHttpClientsManager.get_client()
        await AsyncHttpClientsManager.aclose()
        AsyncHttpClientsManager.create_client(AsyncHttpClientConfig())
        self.assertIsNot(first, AsyncHttpClientsManager.get_client())

    async def test_returned_client_uses_httpx_transport(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ok"})
        )
        client = httpx.AsyncClient(transport=transport)
        with patch("async_http_client.httpx.AsyncClient", return_value=client):
            AsyncHttpClientsManager.create_client(AsyncHttpClientConfig())
        response = await AsyncHttpClientsManager.get_client().get("https://example.test/status")
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_close_attempts_all_clients_before_raising(self):
        first = AsyncMock(spec=httpx.AsyncClient)
        second = AsyncMock(spec=httpx.AsyncClient)
        first.aclose.side_effect = RuntimeError("close failed")
        with patch("async_http_client.httpx.AsyncClient", side_effect=[first, second]):
            AsyncHttpClientsManager.create_client(AsyncHttpClientConfig())
            AsyncHttpClientsManager.create_client(AsyncHttpClientConfig(name="other"))
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            await AsyncHttpClientsManager.aclose()
        first.aclose.assert_awaited_once()
        second.aclose.assert_awaited_once()
        self.assertEqual(AsyncHttpClientsManager()._pools, {})

    def register_transport(self, handler, config=None):
        config = config or AsyncHttpClientConfig()
        # Keep production configuration while replacing only the network transport.
        factory = httpx.AsyncClient
        transport = httpx.MockTransport(handler)
        with patch(
            "async_http_client.httpx.AsyncClient",
            side_effect=lambda **kwargs: factory(transport=transport, **kwargs),
        ):
            AsyncHttpClientsManager.create_client(config)
        return AsyncHttpClientsManager.get_client(config.name)

    async def test_get_configuration_and_application_response(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://example.test/api/items?page=2")
            self.assertEqual(request.headers["Authorization"], "Bearer synthetic-token")
            self.assertEqual(request.headers["X-Default"], "yes")
            self.assertEqual(request.headers["X-Request"], "yes")
            self.assertEqual(request.extensions["timeout"]["read"], 12.0)
            return httpx.Response(200, json={"items": []}, headers={"X-Result": "ok"})

        config = AsyncHttpClientConfig(
            base_url="https://example.test/api/", bearer_token="synthetic-token",
            headers={"X-Default": "yes"}, timeout=12.0,
            max_connections=10, max_keepalive_connections=5,
        )
        client = self.register_transport(handler, config)
        self.assertIsInstance(client, AsyncHttpClient)
        self.assertNotIsInstance(client, httpx.AsyncClient)
        response = await client.get("items", params={"page": 2}, headers={"X-Request": "yes"})
        self.assertIsInstance(response, HttpResponse)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-result"], "ok")
        self.assertEqual(response.json(), {"items": []})
        self.assertIn('"items"', response.text)
        self.assertIsInstance(response.content, bytes)
        self.assertNotIn("synthetic-token", repr(config))

    async def test_post_json_form_and_raw_body(self):
        requests = []
        client = self.register_transport(
            lambda request: (requests.append(request) or httpx.Response(201, text="created")),
            AsyncHttpClientConfig(base_url="https://example.test"),
        )
        response = await client.post("/items", json={"value": 1})
        self.assertEqual(response.text, "created")
        self.assertEqual(requests[-1].method, "POST")
        self.assertEqual(requests[-1].content, b'{"value":1}')
        await client.post("/items", data={"value": "one"})
        self.assertEqual(requests[-1].content, b"value=one")
        await client.post("/items", content=b"raw")
        self.assertEqual(requests[-1].content, b"raw")

    async def test_non_2xx_errors_carry_application_response(self):
        for status in (301, 400, 401, 404, 500):
            with self.subTest(status=status):
                config = AsyncHttpClientConfig(name=str(status), base_url="https://example.test")
                client = self.register_transport(
                    lambda request: httpx.Response(status, json={"error": "synthetic"}), config,
                )
                with self.assertRaises(HttpStatusError) as raised:
                    await client.get("/failure")
                self.assertIsInstance(raised.exception, HttpClientError)
                self.assertEqual(raised.exception.response.status_code, status)
                self.assertEqual(raised.exception.response.json(), {"error": "synthetic"})

    async def test_transport_errors_are_translated_without_sensitive_messages(self):
        for original, expected in (
            (httpx.ReadTimeout, HttpTimeoutError),
            (httpx.ConnectError, HttpConnectionError),
            (httpx.RemoteProtocolError, HttpTransportError),
        ):
            with self.subTest(original=original):
                self.error_log.reset_mock()
                def handler(request):
                    raise original("synthetic-secret", request=request)

                client = self.register_transport(handler, AsyncHttpClientConfig(name=original.__name__))
                with self.assertRaises(expected) as raised:
                    await client.get("https://example.test")
                self.assertIsNone(raised.exception.response)
                self.assertNotIn("synthetic-secret", str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)
                self.error_log.assert_called_once_with(str(raised.exception))
                self.assertNotIn("synthetic-secret", str(self.error_log.call_args))

    async def test_json_decoding_is_on_demand_and_empty_success_is_valid(self):
        client = self.register_transport(lambda request: httpx.Response(204))
        response = await client.get("https://example.test")
        self.assertEqual(response.content, b"")
        with self.assertRaises(ValueError):
            response.json()
        self.error_log.assert_called_once_with("HTTP response JSON decoding failed.")

    async def test_cancellation_is_not_wrapped(self):
        async def handler(request):
            raise asyncio.CancelledError()

        client = self.register_transport(handler)
        with self.assertRaises(asyncio.CancelledError):
            await client.get("https://example.test")
        self.error_log.assert_not_called()

    async def test_using_closed_client_raises_application_error(self):
        AsyncHttpClientsManager.create_client(AsyncHttpClientConfig())
        client = AsyncHttpClientsManager.get_client()
        await AsyncHttpClientsManager.aclose()
        with self.assertRaisesRegex(HttpClientError, "closed"):
            await client.get("https://example.test")


    async def test_creation_failure_logs_and_preserves_original_exception(self):
        original = ValueError("synthetic-secret")
        with patch("async_http_client.httpx.AsyncClient", side_effect=original):
            with self.assertRaises(ValueError) as raised:
                AsyncHttpClientsManager.create_client(AsyncHttpClientConfig())
        self.assertIs(raised.exception, original)
        self.error_log.assert_called_once_with("HTTP client creation failed; error_type=%s.", "ValueError")
        self.assertEqual(AsyncHttpClientsManager()._pools, {})

    async def test_missing_transport_dependency_has_safe_install_hint(self):
        original = ImportError("synthetic-secret")
        with patch("async_http_client.httpx.AsyncClient", side_effect=original):
            with self.assertRaises(ImportError) as raised:
                AsyncHttpClient(AsyncHttpClientConfig())
        self.assertIs(raised.exception, original)
        self.error_log.assert_called_once_with(
            "HTTP client creation failed; error_type=%s; "
            "a transport dependency is missing. Install config/requirements.txt.",
            "ImportError",
        )

    async def test_unexpected_request_failure_logs_and_preserves_exception(self):
        original = ValueError("synthetic-secret")

        def handler(request):
            raise original

        client = self.register_transport(handler)
        with self.assertRaises(ValueError) as raised:
            await client.get("https://example.test")
        self.assertIs(raised.exception, original)
        self.error_log.assert_called_once_with("HTTP request execution failed.")

    async def test_request_debug_logs_config_status_and_redacted_response(self):
        messages = []
        client = self.register_transport(
            lambda request: httpx.Response(401, json={
                "message": "denied", "access_token": "synthetic-secret",
                "echo": "synthetic-secret",
                "nested": {"Authorization": "Bearer synthetic-secret"},
            }),
            AsyncHttpClientConfig(bearer_token="synthetic-secret", timeout=7.0),
        )
        with patch("async_http_client.Logger.DEBUG", side_effect=lambda message, *args: messages.append(message % args)):
            with self.assertRaises(HttpStatusError):
                await client.get("https://example.test")
        output = "\n".join(messages)
        self.assertIn("timeout=7.0", output)
        self.assertIn("status=401", output)
        self.assertIn("denied", output)
        self.assertIn("<redacted>", output)
        self.assertNotIn("synthetic-secret", output)
