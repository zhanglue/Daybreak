"""Explicit Garmin endpoint allowlist with client-derived MCP parameter schemas."""

from datetime import date, datetime
import inspect
from typing import get_type_hints
from zoneinfo import ZoneInfo

from fastmcp.exceptions import ToolError

from garmin_connect_client import GarminConnectClient
from garmin_data_store import CacheMode
from logger import Logger

API_TOOLS = {
    'get_activity': 'Read one activity, including the summary and available performance metrics.',
    'get_activity_workouts': 'Read the structured workout followed during an activity.',
    'search_activities': 'Search one page of activities using every supported filter. Paginate with start and limit (1..99).',
    'get_heart_rate_zones': 'Read sport-specific heart-rate zones; choose whether Garmin generates defaults.',
    'download_activity': 'Download the original activity ZIP to the local store. Returns metadata and a binary MCP resource URI, not inline bytes.',
    'get_fitness_age': 'Read fitness age for a date, optionally scanning full history.',
    'get_effective_weight_goals': 'Read weight goals effective over a date range.',
    'get_daily_hrv': 'Read overnight HRV readings, seven-day average, personal baseline and status.',
    'get_daily_hrv_summaries': 'Read daily HRV summaries over a date range.',
    'get_daily_food_logs': 'Read nutrition logs with optional goals, nutrition, media and meal selection.',
    'get_menstrual_cycle_summary': 'Read menstrual-cycle summary and predictions for a date.',
    'get_menstrual_cycle_day_view': 'Read menstrual-cycle day details with all analysis and response options.',
    'get_daily_sleep': 'Read one night of sleep, stages, scores and available overnight vitals.',
    'get_daily_sleep_summaries': 'Read sleep summaries over up to 31 inclusive dates.',
    'get_user_profile_settings': 'Read user profile settings, units and timezone preferences.',
    'get_daily_hydration': 'Read daily hydration over up to 31 inclusive dates.',
    'get_daily_steps': 'Read daily steps over up to 28 inclusive dates.',
    'get_daily_stress': 'Read daily stress over up to 28 inclusive dates.',
    'get_daily_user_summary': 'Read one calendar day of wellness totals and recovery indicators.',
    'get_daily_summaries': 'Read daily wellness summaries over up to 365 inclusive dates.',
    'get_all_weight_measurements': 'Read all weight measurements over a date range.',
    'get_weight_measurements': 'Read weight summaries over a range; include_all controls individual measurements.',
    'get_daily_body_battery': 'Read Body Battery over up to 31 inclusive dates with optional intraday chunks.',
    'get_daily_spo2': 'Read daily pulse-ox readings and available hourly summaries.',
    'get_daily_heart_rate': 'Read daily heart-rate readings and resting/minimum/maximum summaries.',
    'get_wellness_activity_summaries': 'Read wellness activity summaries over a date range.',
}

RANGE_LIMITS = {
    'get_daily_steps': 28, 'get_daily_stress': 28, 'get_daily_hydration': 31,
    'get_daily_sleep_summaries': 31, 'get_daily_body_battery': 31,
    'get_daily_summaries': 365,
}


def register_api_tools(server, store, finish, timezone_name):
    """Expose only the 26 reviewed remote methods, never client lifecycle methods."""
    for endpoint, description in API_TOOLS.items():
        tool = _make_tool(endpoint, store, finish, timezone_name)
        server.tool(tool, name=endpoint, description=description +
                    ' Uses local-first persistence. cache_mode is prefer_local, local_only, or refresh.'
                    ' Dates are YYYY-MM-DD; omitted dates retain Garmin defaults.'
                    ' Source units/fields are preserved; missing values are not zero.',
                    annotations={'readOnlyHint': True})

    @server.resource('daybreak://activities/{activity_id}/{sha256}', mime_type='application/zip',
                     description='Read an original activity ZIP previously persisted by download_activity. Never fetches remotely.')
    async def activity_archive(activity_id: str, sha256: str) -> bytes:
        return store.read_archive(activity_id, sha256)


def _make_tool(endpoint, store, finish, timezone_name):
    original = getattr(GarminConnectClient, endpoint)
    hints = get_type_hints(original)
    parameters = [p.replace(annotation=hints[p.name]) for p in inspect.signature(original).parameters.values()
                  if p.name != 'self']
    parameters.append(inspect.Parameter('cache_mode', inspect.Parameter.KEYWORD_ONLY,
                                        default='prefer_local', annotation=CacheMode))
    signature = inspect.Signature(parameters, return_annotation=dict)

    async def tool(**arguments):
        bound = signature.bind(**arguments)
        bound.apply_defaults()
        params = dict(bound.arguments)
        mode = params.pop('cache_mode')
        today = datetime.now(ZoneInfo(timezone_name)).date()
        implicit_date = False
        for key in ('calendar_date', 'start_date', 'end_date', 'today_date'):
            if key not in params:
                continue
            if params[key] is None:
                implicit_date = True
                continue
            try:
                value = params[key] if isinstance(params[key], date) else date.fromisoformat(params[key])
            except (TypeError, ValueError):
                Logger.ERROR('Invalid MCP endpoint date.')
                raise ToolError('Dates must be valid ISO calendar dates.') from None
            params[key] = value.isoformat()
        start, end = params.get('start_date'), params.get('end_date')
        if start and end:
            span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
            if span < 1 or (endpoint in RANGE_LIMITS and span > RANGE_LIMITS[endpoint]):
                Logger.ERROR('Invalid MCP endpoint date range.')
                raise ToolError('Invalid date order or endpoint range limit; split the request.')
        if 'activity_id' in params:
            value = params['activity_id']
            if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit() or int(value) <= 0:
                Logger.ERROR('Invalid MCP activity identifier.')
                raise ToolError('Activity ID must be a positive integer.')
            params['activity_id'] = int(value)
        if endpoint == 'search_activities':
            if (params['start'] < 0 or not 1 <= params['limit'] <= 99 or
                    params['favorite'] not in (-1, 0, 1) or params['sort_order'] not in ('asc', 'desc')):
                Logger.ERROR('Invalid MCP activity search options.')
                raise ToolError('Use start >= 0, limit 1..99, favorite -1/0/1 and sort_order asc/desc.')
        if 'activity_id' in params:
            folder = f"activities/{params['activity_id']}"
        elif params.get('calendar_date'):
            folder = params['calendar_date']
        elif 'start_date' in params:
            folder = 'ranges'
        else:
            folder = 'profile' if endpoint in ('get_user_profile_settings', 'get_heart_rate_zones') else 'requests'
        dated_end = None if implicit_date else params.get('calendar_date') or end
        record = await store.read(endpoint, params, folder, mode=mode,
                                  dated_end=date.fromisoformat(dated_end) if dated_end else None,
                                  cache_context=today.isoformat() if implicit_date else None)
        return finish([record])

    tool.__name__ = endpoint
    tool.__signature__ = signature
    tool.__annotations__ = {p.name: p.annotation for p in parameters} | {'return': dict}
    return tool
