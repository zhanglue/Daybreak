# Garmin Connect Client Endpoints

Source: [official Garmin Personal API Swagger](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/),
API specification version **1.0.0**, retrieved on 2026-10-31 from the page's
embedded specification (OpenAPI format 3.0.1). `GarminConnectClient.SWAGGER_VERSION`
records the targeted version and `GarminConnectClient.SWAGGER_URL` records this URL.
All 26 GET paths and their declared parameters have been checked against that
specification. `tests/fixtures/garmin_openapi_parameters.json` retains only the
public parameter contract for offline checks; it contains no account data.

`await GarminConnectClient.get_client()` returns the authenticated singleton.
All data methods use `@token_check`. JSON structure is preserved, empty responses
return `None`, and `download_activity` returns bytes with
`Accept: application/x-zip-compressed`. No files are written or extracted.

Python parameter names use snake case. Query date arguments are optional where
Swagger marks them optional; omitted values are not sent. Dates accept `date` or
ISO strings. Path dates and activity IDs remain required. Boolean values serialize
as lowercase strings. List filters serialize as repeated query parameters.

| Method | GET path | Python parameters (wire names) |
| --- | --- | --- |
| `get_activity` | `/activity-service/activity/{activityId}` | `activity_id` → `activityId` (required) |
| `get_activity_workouts` | `/activity-service/activity/{activityId}/workouts` | `activity_id` → `activityId` (required) |
| `search_activities` | `/activitylist-service/activities/search/activities` | `start` (default `0`); `limit` (default `99`); `favorite` (default `-1`); `sort_order` → `sortOrder` (default `desc`); `exclude_children` → `excludeChildren` (default `true`); `sort_by` → `sortBy` (default `none`); `search` (default `none`); `activity_type` → `activityType` (default `none`); `activity_sub_type` → `activitySubType` (default `none`); `event_type` → `eventType` (default `none`); `min_distance` → `minDistance` (default `none`); `max_distance` → `maxDistance` (default `none`); `min_duration` → `minDuration` (default `none`); `max_duration` → `maxDuration` (default `none`); `min_elevation` → `minElevation` (default `none`); `max_elevation` → `maxElevation` (default `none`); `start_date` → `startDate` (default `none`); `end_date` → `endDate` (default `none`); `upper_latitude` → `upperLatitude` (default `none`); `right_longitude` → `rightLongitude` (default `none`); `lower_latitude` → `lowerLatitude` (default `none`); `left_longitude` → `leftLongitude` (default `none`); `lower_max_depth` → `lowerMaxDepth` (default `none`); `upper_max_depth` → `upperMaxDepth` (default `none`); `deco_dive` → `decoDive` (default `none`); `min_elapsed_duration` → `minElapsedDuration` (default `none`); `max_elapsed_duration` → `maxElapsedDuration` (default `none`); `min_bottom_time` → `minBottomTime` (default `none`); `max_bottom_time` → `maxBottomTime` (default `none`); `min_avg_power` → `minAvgPower` (default `none`); `excluded_activity_sub_type` → `excludedActivitySubType` (default `none`); `required_field` → `requiredField` (default `none`) |
| `get_heart_rate_zones` | `/biometric-service/heartRateZones/v2` | `generate_defaults` → `generateDefaults` (default `true`) |
| `download_activity` | `/download-service/files/activity/{activityId}` | `activity_id` → `activityId` (required) |
| `get_fitness_age` | `/fitnessage-service/fitnessage/v2/{calendarDate}` | `calendar_date` → `calendarDate` (required); `full_history_scan` → `fullHistoryScan` (default `true`) |
| `get_effective_weight_goals` | `/goal-service/goal/user/effective/weightgoal/{startDate}/{endDate}` | `start_date` → `startDate` (required); `end_date` → `endDate` (required) |
| `get_daily_hrv` | `/hrv-service/hrv/{calendarDate}` | `calendar_date` → `calendarDate` (required) |
| `get_daily_hrv_summaries` | `/hrv-service/hrv/daily/{fromDate}/{toDate}` | `start_date` → `fromDate` (required); `end_date` → `toDate` (required) |
| `get_daily_food_logs` | `/nutrition-service/food/logs/{date}` | `include_goals` → `includeGoals` (default `true`); `include_nutrition` → `includeNutrition` (default `true`); `include_media` → `includeMedia` (default `true`); `meal_id` → `mealId` (default `none`); `calendar_date` → `date` (required) |
| `get_menstrual_cycle_summary` | `/periodichealth-service/menstrualcycle/summary/{calendarDate}` | `calendar_date` → `calendarDate` (required) |
| `get_menstrual_cycle_day_view` | `/periodichealth-service/menstrualcycle/dayview/{calendarDate}` | `calendar_date` → `calendarDate` (required); `today_date` → `todayDate` (default `none`); `reduced_response` → `reducedResponse` (default `false`); `skip_bm` → `skipbm` (default `false`); `include_analysis` → `includeAnalysis` (default `false`) |
| `get_daily_sleep` | `/sleep-service/sleep/dailySleep` | `calendar_date` → `date` (default `none`) |
| `get_daily_sleep_summaries` | `/sleep-service/sleep/dailySleepSummariesByDate` | `start_date` → `startDate` (default `none`); `end_date` → `endDate` (default `none`) |
| `get_user_profile_settings` | `/userprofile-service/userprofile/settings` | None |
| `get_daily_hydration` | `/usersummary-service/stats/hydration/daily/{startDate}/{endDate}` | `start_date` → `startDate` (required); `end_date` → `endDate` (required) |
| `get_daily_steps` | `/usersummary-service/stats/steps/daily/{startDate}/{endDate}` | `start_date` → `startDate` (required); `end_date` → `endDate` (required) |
| `get_daily_stress` | `/usersummary-service/stats/stress/daily/{startDate}/{endDate}` | `start_date` → `startDate` (required); `end_date` → `endDate` (required) |
| `get_daily_user_summary` | `/usersummary-service/usersummary/daily` | `calendar_date` → `calendarDate` (default `none`) |
| `get_daily_summaries` | `/usersummary-service/v2/dailysummaries` | `start_date` → `startDate` (default `none`); `end_date` → `endDate` (default `none`) |
| `get_all_weight_measurements` | `/weight-service/weight/all/{startDate}/{endDate}` | `start_date` → `startDate` (required); `end_date` → `endDate` (required) |
| `get_weight_measurements` | `/weight-service/weight/range/{startDate}/{endDate}` | `start_date` → `startDate` (required); `end_date` → `endDate` (required); `include_all` → `includeAll` (default `false`) |
| `get_daily_body_battery` | `/wellness-service/wellness/bodyBattery/reports/daily` | `start_date` → `startDate` (default `none`); `end_date` → `endDate` (default `none`); `chunks` (default `none`) |
| `get_daily_spo2` | `/wellness-service/wellness/daily/spo2acclimation/{calendarDate}` | `calendar_date` → `calendarDate` (required) |
| `get_daily_heart_rate` | `/wellness-service/wellness/dailyHeartRate` | `calendar_date` → `date` (default `none`) |
| `get_wellness_activity_summaries` | `/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}` | `start_date` → `fromDate` (required); `end_date` → `untilDate` (required) |

`None` defaults mean that the query parameter is omitted. In activity search,
`sort_by=None` leaves Garmin's documented `startLocal` sorting default in effect.
`favorite` uses -1 for no filter, 0 for non-favorites, and 1 for favorites;
`sort_order` accepts ascending or descending direction. Activity type and subtype
filters must identify compatible Garmin types. Location filtering requires all
four geographic bounds. Distance/elevation are in meters, durations in seconds,
dive depth in centimeters, and average power in watts.

The Swagger descriptions specify these server-side maximum date ranges:

- Steps and stress: 28 days.
- Hydration, sleep summaries, and Body Battery: 31 days.
- Daily summaries: one year.

These descriptions do not define machine-readable minimum/maximum constraints
for all inputs. The client validates date syntax and positive activity IDs;
range limits, ordering, filter semantics, and other server-side validation remain
Garmin's responsibility. The client does not split requests or paginate implicitly.

All 26 remote methods use `@handle_api_errors` outside `@token_check`. HTTP status,
network/timeout/transport errors, and `ValueError` from validation, token refresh,
or response parsing are logged through `Logger.ERROR` and return `None`. Logs
include only the method name, safe category, and HTTP status when available;
raw exception text and response bodies are excluded. Lower transport/validation
layers may also log the original failure under the repository logging rule.
`None` can therefore mean a remote failure, an empty response, or JSON null;
callers must not treat it as a successful measurement. Download methods also
return `None` on handled failures. Cancellation and unrelated programming errors
continue to propagate. Initial factory authentication and explicit shutdown are
outside this decorator: initialization must still fail without publishing a client.

Automated tests verify parameter contracts using synthetic data. Separately, on
2026-10-31 the user confirmed successful live Garmin validation. That confirmation
does not claim that every endpoint or error path was exercised. No credentials or
real account responses are stored in the repository. Future agent access to real
Garmin data must continue through authorized Daybreak MCP tools. Token storage is intentionally process-local; the long-running MCP
server reuses it, and restarting the process obtains a new token. Disk persistence
is outside the agreed client scope. Existing generic HTTP DEBUG JSON response
previews are retained by user decision for this personal application.
Authentication-status recovery remains outside the current implementation.
