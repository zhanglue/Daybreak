"""Synthetic endpoint routing, authentication, and response contract checks."""

import asyncio
import inspect
import json
from pathlib import Path
from datetime import date
import unittest
from unittest.mock import AsyncMock, patch

from async_http_client import HttpResponse, HttpStatusError
from garmin_connect_client import GarminConnectClient


class GarminEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = object.__new__(GarminConnectClient)
        self.client._token = "synthetic-token"
        self.client._token_expires_at = float("inf")
        self.client._token_lock = asyncio.Lock()
        self.client._http_client = AsyncMock()
        self.client._http_client.get.return_value = HttpResponse(
            200, {}, b'{"synthetic":true}', '{"synthetic":true}'
        )

    async def test_all_endpoint_routes_and_bearer_headers(self):
        day, end = "2026-10-01", "2026-10-02"
        dates = (date(2026, 10, 1), end)
        cases = [
            ("get_activity", (123,), {}, "/activity-service/activity/123", None),
            ("get_activity_workouts", (123,), {}, "/activity-service/activity/123/workouts", None),
            ("get_heart_rate_zones", (), {}, "/biometric-service/heartRateZones/v2", {"generateDefaults": "true"}),
            ("get_fitness_age", (day,), {}, f"/fitnessage-service/fitnessage/v2/{day}", {"fullHistoryScan": "true"}),
            ("get_effective_weight_goals", dates, {}, f"/goal-service/goal/user/effective/weightgoal/{day}/{end}", None),
            ("get_daily_hrv", (day,), {}, f"/hrv-service/hrv/{day}", None),
            ("get_daily_hrv_summaries", dates, {}, f"/hrv-service/hrv/daily/{day}/{end}", None),
            ("get_daily_food_logs", (day,), {}, f"/nutrition-service/food/logs/{day}", {"includeGoals": "true", "includeNutrition": "true", "includeMedia": "true"}),
            ("get_menstrual_cycle_summary", (day,), {}, f"/periodichealth-service/menstrualcycle/summary/{day}", None),
            ("get_user_profile_settings", (), {}, "/userprofile-service/userprofile/settings", None),
            ("get_daily_hydration", dates, {}, f"/usersummary-service/stats/hydration/daily/{day}/{end}", None),
            ("get_daily_steps", dates, {}, f"/usersummary-service/stats/steps/daily/{day}/{end}", None),
            ("get_daily_stress", dates, {}, f"/usersummary-service/stats/stress/daily/{day}/{end}", None),
            ("get_weight_measurements", dates, {}, f"/weight-service/weight/range/{day}/{end}", {"includeAll": "false"}),
            ("get_daily_spo2", (day,), {}, f"/wellness-service/wellness/daily/spo2acclimation/{day}", None),
            ("get_wellness_activity_summaries", dates, {}, f"/wellnessactivity-service/activity/summary/range/{day}/{end}", None),
            ("get_all_weight_measurements", dates, {}, f"/weight-service/weight/all/{day}/{end}", None),
            ("get_daily_sleep", (day,), {}, "/sleep-service/sleep/dailySleep", {"date": day}),
            ("get_daily_sleep_summaries", dates, {}, "/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": day, "endDate": end}),
            ("get_daily_summaries", dates, {}, "/usersummary-service/v2/dailysummaries", {"startDate": day, "endDate": end}),
            ("get_daily_heart_rate", (day,), {}, "/wellness-service/wellness/dailyHeartRate", {"date": day}),
            ("get_menstrual_cycle_day_view", dates, {}, f"/periodichealth-service/menstrualcycle/dayview/{day}", {"todayDate": end, "reducedResponse": "false", "skipbm": "false", "includeAnalysis": "false"}),
            ("search_activities", (), {"start": 5, "limit": 10, "start_date": day, "end_date": end, "activity_type": "running"}, "/activitylist-service/activities/search/activities", {"start": 5, "limit": 10, "startDate": day, "endDate": end, "activityType": "running", "favorite": -1, "sortOrder": "desc", "excludeChildren": "true"}),
            ("get_daily_body_battery", dates, {"chunks": 2}, "/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": day, "endDate": end, "chunks": 2}),
            ("get_daily_user_summary", (day,), {}, "/usersummary-service/usersummary/daily", {"calendarDate": day}),
        ]
        for name, args, kwargs, path, params in cases:
            with self.subTest(method=name):
                self.client._http_client.get.reset_mock()
                method = getattr(self.client, name)
                self.assertTrue(hasattr(method, "__wrapped__"))
                self.assertEqual(await method(*args, **kwargs), {"synthetic": True})
                self.client._http_client.get.assert_awaited_once_with(
                    path, params=params,
                    headers={"Authorization": "Bearer synthetic-token", "Accept": "application/json"},
                )
        self.client._http_client.get.return_value = HttpResponse(200, {}, b"synthetic-download", "")
        self.assertEqual(await self.client.download_activity(123), b"synthetic-download")
        self.assertTrue(hasattr(self.client.download_activity, "__wrapped__"))
        self.client._http_client.get.assert_awaited_with(
            "/download-service/files/activity/123",
            headers={"Authorization": "Bearer synthetic-token", "Accept": "application/x-zip-compressed"},
        )

    async def test_optional_queries_are_omitted_and_empty_response_is_none(self):
        await self.client.search_activities()
        self.assertEqual(self.client._http_client.get.call_args.kwargs["params"], {"start": 0, "limit": 99, "favorite": -1, "sortOrder": "desc", "excludeChildren": "true"})
        await self.client.get_daily_body_battery("2026-10-01", "2026-10-02")
        self.assertNotIn("chunks", self.client._http_client.get.call_args.kwargs["params"])
        self.client._http_client.get.return_value = HttpResponse(204, {}, b"", "")
        self.assertIsNone(await self.client.get_heart_rate_zones())

    async def test_remote_method_sends_refreshed_token_and_handles_http_errors(self):
        self.client._token_expires_at = 0
        with patch.object(self.client, "_request_token", return_value=("new-token", float("inf"))) as refresh:
            await self.client.get_heart_rate_zones()
            refresh.assert_awaited_once()
        self.assertEqual(self.client._http_client.get.call_args.kwargs["headers"]["Authorization"], "Bearer new-token")
        error = HttpStatusError("synthetic", HttpResponse(403, {}, b"", ""))
        self.client._http_client.get.side_effect = error
        with patch("garmin_connect_client.Logger.ERROR") as log:
            self.assertIsNone(await self.client.get_heart_rate_zones())
            log.assert_called_once_with(
                "Garmin remote operation failed; method=%s; status=%d.",
                "get_heart_rate_zones", 403,
            )

    async def test_invalid_path_arguments_log_and_prevent_requests(self):
        for method, argument in ((self.client.get_activity, "../profile"),
                                 (self.client.download_activity, 0),
                                 (self.client.get_daily_sleep, "2026-02-30")):
            with self.subTest(argument=argument), patch("garmin_connect_client.Logger.ERROR") as log:
                self.assertIsNone(await method(argument))
                self.assertTrue(log.called)
                self.assertNotIn(str(argument), str(log.call_args_list))
        self.client._http_client.get.assert_not_awaited()

    async def test_official_parameter_contract_signatures_and_wire_values(self):
        contract = json.loads((Path(__file__).parent / "fixtures/garmin_openapi_parameters.json").read_text())
        for endpoint in contract["endpoints"]:
            with self.subTest(method=endpoint["method"]):
                method = getattr(self.client, endpoint["method"])
                signature = inspect.signature(method)
                self.assertEqual(set(signature.parameters), {param["python_name"] for param in endpoint["parameters"]})
                supplied, expected_query = {}, {}
                path = endpoint["path"]
                for param in endpoint["parameters"]:
                    schema, name = param["schema"], param["python_name"]
                    expected_default = inspect.Parameter.empty if param["required"] else schema.get("default")
                    self.assertEqual(signature.parameters[name].default, expected_default)
                    if schema.get("format") == "date":
                        value = date(2026, 10, 1)
                        wire = "2026-10-01"
                    elif schema["type"] == "boolean":
                        value = not schema.get("default", False)
                        wire = str(value).lower()
                    elif schema["type"] == "array":
                        value = wire = ["synthetic-one", "synthetic-two"]
                    elif schema["type"] == "integer":
                        value = wire = 7
                    elif schema["type"] == "number":
                        value = wire = 1.5
                    else:
                        value = wire = "synthetic-filter"
                    supplied[name] = value
                    if param["in"] == "path":
                        path = path.replace("{" + param["name"] + "}", str(wire))
                    else:
                        expected_query[param["name"]] = wire
                self.client._http_client.get.reset_mock()
                await method(**supplied)
                actual = self.client._http_client.get.call_args
                self.assertEqual(actual.args, (path,))
                self.assertEqual(actual.kwargs.get("params"), expected_query or None)

    async def test_optional_dates_can_be_omitted(self):
        for name in ("get_daily_sleep", "get_daily_sleep_summaries", "get_daily_summaries",
                     "get_daily_body_battery", "get_daily_heart_rate", "get_daily_user_summary"):
            with self.subTest(method=name):
                await getattr(self.client, name)()
                self.assertIsNone(self.client._http_client.get.call_args.kwargs["params"])

    async def test_array_query_values_are_repeated_by_httpx(self):
        import httpx
        from async_http_client import AsyncHttpClient, AsyncHttpClientConfig

        observed = []
        def handle(request):
            observed.append(request)
            return httpx.Response(200, json=[])

        transport = AsyncHttpClient(AsyncHttpClientConfig(base_url="https://synthetic.test"))
        await transport._client.aclose()
        transport._client = httpx.AsyncClient(base_url="https://synthetic.test", transport=httpx.MockTransport(handle))
        self.client._http_client = transport
        try:
            await self.client.search_activities(excluded_activity_sub_type=["one", "two"], required_field=["power", "distance"])
            self.assertEqual(observed[0].url.params.get_list("excludedActivitySubType"), ["one", "two"])
            self.assertEqual(observed[0].url.params.get_list("requiredField"), ["power", "distance"])
        finally:
            await transport.aclose()

    async def test_expected_remote_failures_return_none_with_safe_logs(self):
        from async_http_client import HttpConnectionError, HttpTimeoutError, HttpTransportError

        failures = [
            HttpStatusError("sensitive-detail", HttpResponse(code, {}, b"private-body", "private-body"))
            for code in (400, 401, 403, 404, 429, 500, 503)
        ] + [HttpConnectionError("sensitive-detail"), HttpTimeoutError("sensitive-detail"),
             HttpTransportError("sensitive-detail")]
        for error in failures:
            with self.subTest(error=type(error).__name__), patch("garmin_connect_client.Logger.ERROR") as log:
                self.client._http_client.get.side_effect = error
                self.assertIsNone(await self.client.get_heart_rate_zones())
                log.assert_called_once()
                self.assertNotIn("sensitive-detail", str(log.call_args))
                self.assertNotIn("private-body", str(log.call_args))

    async def test_json_and_refresh_failures_return_none(self):
        with patch("garmin_connect_client.Logger.ERROR"):
            self.client._http_client.get.return_value = HttpResponse(200, {}, b"invalid-json", "invalid-json")
            self.assertIsNone(await self.client.get_heart_rate_zones())
            self.client._http_client.get.reset_mock()
            self.client._token_expires_at = 0
            with patch.object(self.client, "_request_token", side_effect=ValueError("sensitive-detail")):
                self.assertIsNone(await self.client.get_heart_rate_zones())
                self.client._http_client.get.assert_not_awaited()

    async def test_cancellation_and_programming_errors_propagate(self):
        for error in (asyncio.CancelledError(), TypeError("synthetic programming error")):
            self.client._http_client.get.side_effect = error
            with patch("garmin_connect_client.Logger.ERROR") as log:
                with self.assertRaises(type(error)):
                    await self.client.get_heart_rate_zones()
                log.assert_not_called()
