"""Standalone Garmin Connect client with a process-local singleton."""

from asyncio import Lock, run
import base64
import json
import math
import sys
from collections.abc import Mapping
from datetime import date
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from time import time
from typing import Any, ClassVar
from urllib.parse import quote

from async_http_client import AsyncHttpClient, AsyncHttpClientConfig, HttpClientError, HttpStatusError
from global_config import GarminConnectClientConfig, GlobalConfig
from logger import Logger


def handle_api_errors(method):
    """Log expected remote-operation failures and return None to the caller."""
    @wraps(method)
    async def handled(self, *args, **kwargs):
        try:
            return await method(self, *args, **kwargs)
        except HttpStatusError as error:
            Logger.ERROR(
                "Garmin remote operation failed; method=%s; status=%d.",
                method.__name__, error.response.status_code,
            )
        except HttpClientError:
            Logger.ERROR("Garmin remote transport failed; method=%s.", method.__name__)
        except ValueError:
            Logger.ERROR("Garmin remote validation or response parsing failed; method=%s.", method.__name__)
        return None
    return handled


def token_check(method):
    """Wait for a usable token before invoking an async remote instance method."""
    @wraps(method)
    async def authenticated(self, *args, **kwargs):
        await self._ensure_token()
        return await method(self, *args, **kwargs)
    return authenticated


class GarminConnectClient:
    """Share one lazily created client across callers in this process.

    Use get_client() on one application event loop. The factory obtains a
    token before publication. Close after all requests have stopped.
    """

    SWAGGER_VERSION: ClassVar[str] = "1.0.0"
    SWAGGER_URL: ClassVar[str] = "https://developer.garmin.com/gc-developer-program/personal/swagger-docs/"

    _instance: ClassVar["GarminConnectClient | None"] = None
    _instance_lock: ClassVar[Lock] = Lock()
    _config: GarminConnectClientConfig
    _token: str
    _token_expires_at: float
    _token_lock: Lock
    _http_client: AsyncHttpClient

    @classmethod
    async def get_client(cls) -> "GarminConnectClient":
        """Create and publish one instance only after initialization succeeds.

        Initialization failures and cancellation leave the singleton unpublished,
        allowing a later call to retry. Use within one application event loop.
        """
        if cls._instance is not None:
            return cls._instance
        async with cls._instance_lock:
            if cls._instance is None:
                instance = object.__new__(cls)
                await instance._initialize()
                cls._instance = instance
        return cls._instance

    @classmethod
    def generate_http_client_config(cls, config: GarminConnectClientConfig) -> AsyncHttpClientConfig:
        """Translate Garmin settings without creating or accessing a singleton."""
        return AsyncHttpClientConfig(
            name=config.http_client_name,
            base_url=config.base_url,
            timeout=config.timeout,
            max_connections=config.http_client_pool_size,
            max_keepalive_connections=config.max_keepalive_connections,
            keepalive_expiry=config.keepalive_expiry,
        )

    @handle_api_errors
    @token_check
    async def get_activity(self, activity_id: int | str) -> Any:
        """GET /activity-service/activity/{activityId}."""
        return await self._get_json(
            f"/activity-service/activity/{GarminConnectClient._format_activity_id(activity_id)}",
        )

    @handle_api_errors
    @token_check
    async def get_activity_workouts(self, activity_id: int | str) -> Any:
        """GET /activity-service/activity/{activityId}/workouts."""
        return await self._get_json(
            f"/activity-service/activity/{GarminConnectClient._format_activity_id(activity_id)}/workouts",
        )

    @handle_api_errors
    @token_check
    async def search_activities(
        self,
        *,
        start: int = 0,
        limit: int = 99,
        favorite: int = -1,
        sort_order: str = 'desc',
        exclude_children: bool = True,
        sort_by: str | None = None,
        search: str | None = None,
        activity_type: str | None = None,
        activity_sub_type: str | None = None,
        event_type: str | None = None,
        min_distance: int | None = None,
        max_distance: int | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        min_elevation: int | None = None,
        max_elevation: int | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        upper_latitude: float | None = None,
        right_longitude: float | None = None,
        lower_latitude: float | None = None,
        left_longitude: float | None = None,
        lower_max_depth: int | None = None,
        upper_max_depth: int | None = None,
        deco_dive: bool | None = None,
        min_elapsed_duration: int | None = None,
        max_elapsed_duration: int | None = None,
        min_bottom_time: int | None = None,
        max_bottom_time: int | None = None,
        min_avg_power: int | None = None,
        excluded_activity_sub_type: list[str] | None = None,
        required_field: list[str] | None = None,
    ) -> Any:
        """GET /activitylist-service/activities/search/activities."""
        params = {
            "start": start,
            "limit": limit,
            "favorite": favorite,
            "sortOrder": sort_order,
            "excludeChildren": exclude_children,
            "sortBy": sort_by,
            "search": search,
            "activityType": activity_type,
            "activitySubType": activity_sub_type,
            "eventType": event_type,
            "minDistance": min_distance,
            "maxDistance": max_distance,
            "minDuration": min_duration,
            "maxDuration": max_duration,
            "minElevation": min_elevation,
            "maxElevation": max_elevation,
            "startDate": GarminConnectClient._format_optional_date(start_date),
            "endDate": GarminConnectClient._format_optional_date(end_date),
            "upperLatitude": upper_latitude,
            "rightLongitude": right_longitude,
            "lowerLatitude": lower_latitude,
            "leftLongitude": left_longitude,
            "lowerMaxDepth": lower_max_depth,
            "upperMaxDepth": upper_max_depth,
            "decoDive": deco_dive,
            "minElapsedDuration": min_elapsed_duration,
            "maxElapsedDuration": max_elapsed_duration,
            "minBottomTime": min_bottom_time,
            "maxBottomTime": max_bottom_time,
            "minAvgPower": min_avg_power,
            "excludedActivitySubType": excluded_activity_sub_type,
            "requiredField": required_field,
        }
        return await self._get_json(
            "/activitylist-service/activities/search/activities", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_heart_rate_zones(self, *, generate_defaults: bool = True) -> Any:
        """GET /biometric-service/heartRateZones/v2."""
        params = {
            "generateDefaults": generate_defaults,
        }
        return await self._get_json(
            "/biometric-service/heartRateZones/v2", params=params,
        )

    @handle_api_errors
    @token_check
    async def download_activity(self, activity_id: int | str) -> bytes | None:
        """GET /download-service/files/activity/{activityId}."""
        response = await self._http_client.get(
            f"/download-service/files/activity/{GarminConnectClient._format_activity_id(activity_id)}",
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/x-zip-compressed"},
        )
        return response.content

    @handle_api_errors
    @token_check
    async def get_fitness_age(self, calendar_date: date | str, *, full_history_scan: bool = True) -> Any:
        """GET /fitnessage-service/fitnessage/v2/{calendarDate}."""
        params = {
            "fullHistoryScan": full_history_scan,
        }
        return await self._get_json(
            f"/fitnessage-service/fitnessage/v2/{GarminConnectClient._format_date(calendar_date)}", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_effective_weight_goals(self, start_date: date | str, end_date: date | str) -> Any:
        """GET /goal-service/goal/user/effective/weightgoal/{startDate}/{endDate}."""
        return await self._get_json(
            f"/goal-service/goal/user/effective/weightgoal/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_daily_hrv(self, calendar_date: date | str) -> Any:
        """GET /hrv-service/hrv/{calendarDate}."""
        return await self._get_json(
            f"/hrv-service/hrv/{GarminConnectClient._format_date(calendar_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_daily_hrv_summaries(self, start_date: date | str, end_date: date | str) -> Any:
        """GET /hrv-service/hrv/daily/{fromDate}/{toDate}."""
        return await self._get_json(
            f"/hrv-service/hrv/daily/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_daily_food_logs(
        self,
        calendar_date: date | str,
        *,
        include_goals: bool = True,
        include_nutrition: bool = True,
        include_media: bool = True,
        meal_id: int | None = None,
    ) -> Any:
        """GET /nutrition-service/food/logs/{date}."""
        params = {
            "includeGoals": include_goals,
            "includeNutrition": include_nutrition,
            "includeMedia": include_media,
            "mealId": meal_id,
        }
        return await self._get_json(
            f"/nutrition-service/food/logs/{GarminConnectClient._format_date(calendar_date)}", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_menstrual_cycle_summary(self, calendar_date: date | str) -> Any:
        """GET /periodichealth-service/menstrualcycle/summary/{calendarDate}."""
        return await self._get_json(
            f"/periodichealth-service/menstrualcycle/summary/{GarminConnectClient._format_date(calendar_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_menstrual_cycle_day_view(
        self,
        calendar_date: date | str,
        today_date: date | str | None = None,
        *,
        reduced_response: bool = False,
        skip_bm: bool = False,
        include_analysis: bool = False,
    ) -> Any:
        """GET /periodichealth-service/menstrualcycle/dayview/{calendarDate}."""
        params = {
            "todayDate": GarminConnectClient._format_optional_date(today_date),
            "reducedResponse": reduced_response,
            "skipbm": skip_bm,
            "includeAnalysis": include_analysis,
        }
        return await self._get_json(
            f"/periodichealth-service/menstrualcycle/dayview/{GarminConnectClient._format_date(calendar_date)}", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_daily_sleep(
        self,
        calendar_date: date | str | None = None,
    ) -> Any:
        """GET /sleep-service/sleep/dailySleep."""
        params = {
            "date": GarminConnectClient._format_optional_date(calendar_date),
        }
        return await self._get_json(
            "/sleep-service/sleep/dailySleep", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_daily_sleep_summaries(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> Any:
        """GET /sleep-service/sleep/dailySleepSummariesByDate."""
        params = {
            "startDate": GarminConnectClient._format_optional_date(start_date),
            "endDate": GarminConnectClient._format_optional_date(end_date),
        }
        return await self._get_json(
            "/sleep-service/sleep/dailySleepSummariesByDate", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_user_profile_settings(self) -> Any:
        """GET /userprofile-service/userprofile/settings."""
        return await self._get_json(
            "/userprofile-service/userprofile/settings",
        )

    @handle_api_errors
    @token_check
    async def get_daily_hydration(self, start_date: date | str, end_date: date | str) -> Any:
        """GET /usersummary-service/stats/hydration/daily/{startDate}/{endDate}."""
        return await self._get_json(
            f"/usersummary-service/stats/hydration/daily/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_daily_steps(self, start_date: date | str, end_date: date | str) -> Any:
        """GET /usersummary-service/stats/steps/daily/{startDate}/{endDate}."""
        return await self._get_json(
            f"/usersummary-service/stats/steps/daily/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_daily_stress(self, start_date: date | str, end_date: date | str) -> Any:
        """GET /usersummary-service/stats/stress/daily/{startDate}/{endDate}."""
        return await self._get_json(
            f"/usersummary-service/stats/stress/daily/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_daily_user_summary(
        self,
        calendar_date: date | str | None = None,
    ) -> Any:
        """GET /usersummary-service/usersummary/daily."""
        params = {
            "calendarDate": GarminConnectClient._format_optional_date(calendar_date),
        }
        return await self._get_json(
            "/usersummary-service/usersummary/daily", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_daily_summaries(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> Any:
        """GET /usersummary-service/v2/dailysummaries."""
        params = {
            "startDate": GarminConnectClient._format_optional_date(start_date),
            "endDate": GarminConnectClient._format_optional_date(end_date),
        }
        return await self._get_json(
            "/usersummary-service/v2/dailysummaries", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_all_weight_measurements(self, start_date: date | str, end_date: date | str) -> Any:
        """GET /weight-service/weight/all/{startDate}/{endDate}."""
        return await self._get_json(
            f"/weight-service/weight/all/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_weight_measurements(self, start_date: date | str, end_date: date | str, *, include_all: bool = False) -> Any:
        """GET /weight-service/weight/range/{startDate}/{endDate}."""
        params = {
            "includeAll": include_all,
        }
        return await self._get_json(
            f"/weight-service/weight/range/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_daily_body_battery(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        *,
        chunks: int | None = None,
    ) -> Any:
        """GET /wellness-service/wellness/bodyBattery/reports/daily."""
        params = {
            "startDate": GarminConnectClient._format_optional_date(start_date),
            "endDate": GarminConnectClient._format_optional_date(end_date),
            "chunks": chunks,
        }
        return await self._get_json(
            "/wellness-service/wellness/bodyBattery/reports/daily", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_daily_spo2(self, calendar_date: date | str) -> Any:
        """GET /wellness-service/wellness/daily/spo2acclimation/{calendarDate}."""
        return await self._get_json(
            f"/wellness-service/wellness/daily/spo2acclimation/{GarminConnectClient._format_date(calendar_date)}",
        )

    @handle_api_errors
    @token_check
    async def get_daily_heart_rate(
        self,
        calendar_date: date | str | None = None,
    ) -> Any:
        """GET /wellness-service/wellness/dailyHeartRate."""
        params = {
            "date": GarminConnectClient._format_optional_date(calendar_date),
        }
        return await self._get_json(
            "/wellness-service/wellness/dailyHeartRate", params=params,
        )

    @handle_api_errors
    @token_check
    async def get_wellness_activity_summaries(self, start_date: date | str, end_date: date | str) -> Any:
        """GET /wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}."""
        return await self._get_json(
            f"/wellnessactivity-service/activity/summary/range/{GarminConnectClient._format_date(start_date)}/{GarminConnectClient._format_date(end_date)}",
        )


    async def aclose(self) -> None:
        """Close owned transport after callers stop; allow factory recreation."""
        async with type(self)._instance_lock:
            await self._http_client.aclose()
            self._token = ""
            self._token_expires_at = 0.0
            if type(self)._instance is self:
                type(self)._instance = None

    def __new__(cls) -> "GarminConnectClient":
        message = "Use await GarminConnectClient.get_client() to create the client."
        Logger.ERROR(message)
        raise TypeError(message)

    async def _initialize(self) -> None:
        """Prepare transport and obtain a token before publication."""
        self._config = GlobalConfig().GarminConnectClient
        self._token = ""
        self._token_expires_at = 0.0
        self._token_lock = Lock()
        self._http_client = AsyncHttpClient(GarminConnectClient.generate_http_client_config(self._config))
        try:
            await self._ensure_token()
        except BaseException:
            await self._http_client.aclose()
            raise

    async def _ensure_token(self) -> None:
        """Serialize checks and refresh within ten minutes of expiration."""
        async with self._token_lock:
            if self._token and self._token_expires_at - time() > 600:
                return
            token, expires_at = await self._request_token()
            self._token, self._token_expires_at = token, expires_at

    async def _request_token(self) -> tuple[str, float]:
        """Exchange a locally loaded key; retain no separate API key member."""
        response = await self._http_client.post(
            "/personalapitoken-service/personal-api/personal-api-key/token",
            headers={"Authorization": f"ApiKey {self._load_api_key()}", "Accept": "*/*"},
        )
        token = response.text.strip()
        try:
            _, encoded_payload, _ = token.split(".")
            payload = json.loads(base64.b64decode(
                encoded_payload + "=" * (-len(encoded_payload) % 4),
                altchars=b"-_", validate=True,
            ))
            expiration = payload.get("exp") if isinstance(payload, dict) else None
            expires_at = float(expiration) if type(expiration) in (int, float) else 0.0
        except (ValueError, TypeError, UnicodeError, OverflowError):
            message = "Garmin token response has no usable JWT expiration."
            Logger.ERROR(message)
            raise ValueError(message) from None
        if not math.isfinite(expires_at) or expires_at - time() <= 600:
            message = "Garmin token response has no usable JWT expiration."
            Logger.ERROR(message)
            raise ValueError(message)
        # The exp claim is used for scheduling, not as a signature verification.
        return token, expires_at

    def _load_api_key(self) -> str:
        """Resolve the configured key lazily, preferring a non-blank inline key."""
        key = self._config.api_key_string.strip()
        if key:
            return key
        if not self._config.api_key_file:
            message = "Garmin API key is not configured."
            Logger.ERROR(message)
            raise ValueError(message)
        root = Path(__file__).resolve().parents[1]
        path = (root / self._config.api_key_file).resolve()
        if not path.is_relative_to(root):
            message = "Garmin API key file must resolve inside the repository."
            Logger.ERROR(message)
            raise ValueError(message)
        try:
            key = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            message = "Garmin API key file could not be read."
            Logger.ERROR(message)
            raise ValueError(message) from None
        if not key:
            message = "Garmin API key file is empty."
            Logger.ERROR(message)
            raise ValueError(message)
        return key

    async def _get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        """Send a guarded endpoint's request using the current bearer token."""
        response = await self._http_client.get(
            path, params={key: (str(value).lower() if isinstance(value, bool) else value)
                          for key, value in (params or {}).items() if value is not None} or None,
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
        )
        return response.json() if response.content else None

    @staticmethod
    def _format_date(value: date | str) -> str:
        """Normalize date arguments to ISO calendar dates."""
        try:
            return date.fromisoformat(str(value)).isoformat()
        except (TypeError, ValueError):
            message = "Garmin date must be a date or an ISO calendar date string."
            Logger.ERROR(message)
            raise ValueError(message) from None

    @staticmethod
    def _format_activity_id(value: int | str) -> str:
        """Require a positive numeric activity identifier for path safety."""
        text = str(value)
        if type(value) not in (int, str) or not text.isascii() or not text.isdecimal() or int(text) <= 0:
            message = "Garmin activity ID must be a positive integer."
            Logger.ERROR(message)
            raise ValueError(message)
        return quote(text, safe="")

    @staticmethod
    def _format_optional_date(value: date | str | None) -> str | None:
        """Normalize an optional date while preserving omission."""
        return GarminConnectClient._format_date(value) if value is not None else None


async def main(args: list[str] | None = None) -> int:
    """Run a standalone smoke test with masked configuration and two GETs."""
    client = None
    exit_code = 1
    try:
        config = GlobalConfig()
        config.update_from_toml(Path(__file__).resolve().parents[1] / "config/default_config.toml")
        config.update_from_cli(args)
        displayed_config = asdict(config.GarminConnectClient)
        displayed_config["api_key_string"] = "********"
        print("GarminConnectClient configuration:")
        print(json.dumps(displayed_config, indent=2, ensure_ascii=False))

        client = await GarminConnectClient.get_client()
        print(f"Token acquired; expires_at={client._token_expires_at}")
        zones = await client.get_heart_rate_zones()
        print("Heart rate zones:")
        print(json.dumps(zones, indent=2, ensure_ascii=False))
        settings = await client.get_user_profile_settings()
        print("User profile settings:")
        print(json.dumps(settings, indent=2, ensure_ascii=False))
        exit_code = 0 if zones is not None and settings is not None else 1
    except Exception:
        Logger.ERROR("Garmin standalone smoke test failed.")
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                Logger.ERROR("Garmin standalone smoke test cleanup failed.")
                exit_code = 1
        Logger.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(run(main()))
