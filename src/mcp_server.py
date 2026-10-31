"""Daybreak local MCP service with local-first Garmin data tools."""

from contextlib import asynccontextmanager
from asyncio import CancelledError
from datetime import date, datetime, timedelta
import json
import logging
import sys
from pathlib import Path
from typing import Literal
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from garmin_connect_client import GarminConnectClient
from garmin_data_store import CacheMode, GarminDataStore
from garmin_mcp_tools import API_TOOLS, register_api_tools
from global_config import GlobalConfig, MCPServerConfig
from logger import Logger

DAILY = {
    'summary': 'get_daily_user_summary', 'sleep': 'get_daily_sleep',
    'hrv': 'get_daily_hrv', 'heart_rate': 'get_daily_heart_rate',
    'spo2': 'get_daily_spo2', 'fitness_age': 'get_fitness_age',
}
RANGES = {
    'weight': 'get_weight_measurements', 'steps': 'get_daily_steps',
    'stress': 'get_daily_stress', 'hydration': 'get_daily_hydration',
    'body_battery': 'get_daily_body_battery',
}
Dataset = Literal['summary', 'sleep', 'hrv', 'heart_rate', 'spo2', 'fitness_age',
                  'weight', 'steps', 'stress', 'hydration', 'body_battery']


class MCPRequestLoggingMiddleware(Middleware):
    """Log safe call metadata through Daybreak, without arguments or results."""

    _tool_names = frozenset(API_TOOLS) | {
        'get_garmin_data', 'get_garmin_day', 'search_garmin_activities',
        'get_garmin_activity', 'get_garmin_profile', 'list_local_garmin_data',
    }

    async def on_call_tool(self, context, call_next):
        name = context.message.name
        tool = name if name in MCPRequestLoggingMiddleware._tool_names else 'unknown'
        return await self._record(context, call_next, 'tools/call', tool)

    async def on_list_tools(self, context, call_next):
        return await self._record(context, call_next, 'tools/list')

    async def on_read_resource(self, context, call_next):
        return await self._record(context, call_next, 'resources/read')

    async def on_list_resources(self, context, call_next):
        return await self._record(context, call_next, 'resources/list')

    async def on_list_resource_templates(self, context, call_next):
        return await self._record(context, call_next, 'resources/templates/list')

    async def _record(self, context, call_next, method, tool='-'):
        call_id = uuid4().hex[:12]
        started = perf_counter()
        status = 'error'
        Logger.INFO('MCP request received; call_id=%s; method=%s; tool=%s.', call_id, method, tool)
        try:
            result = await call_next(context)
            payload = getattr(result, 'structured_content', None)
            status = 'error' if getattr(result, 'is_error', False) else 'ok'
            if isinstance(payload, dict) and payload.get('status') in ('ok', 'partial', 'error'):
                status = payload['status']
            return result
        finally:
            if status == 'error' and isinstance(sys.exception(), CancelledError):
                status = 'cancelled'
            Logger.INFO('MCP request finished; call_id=%s; method=%s; tool=%s; status=%s; elapsed_ms=%.1f.',
                        call_id, method, tool, status, (perf_counter() - started) * 1000)


def create_server(config: MCPServerConfig | None = None, *, store: GarminDataStore | None = None) -> FastMCP:
    """Build tools without credentials, network access, or filesystem creation."""
    config = config if config is not None else GlobalConfig().MCPServer
    if config.data_source != 'garmin_connect':
        Logger.ERROR('MCP data source is not implemented.')
        raise NotImplementedError('MCP data source is not implemented.')
    if store is None:
        root = Path(__file__).resolve().parents[1]
        store = GarminDataStore(root / config.data_directory, config,
                                client_factory=GarminConnectClient.get_client)
    calendar_zone = ZoneInfo(config.timezone_name)

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield
        finally:
            await store.aclose()

    server = FastMCP('Daybreak', lifespan=lifespan, mask_error_details=True,
                     middleware=[MCPRequestLoggingMiddleware()],
                     instructions='Read local Garmin data first. Check freshness, errors, '
                     'units and coverage before analysis. Never infer zero from missing data.')

    def dates(start_date, end_date):
        end_date = end_date or start_date
        if start_date > end_date or (end_date - start_date).days >= 31 or end_date > datetime.now(calendar_zone).date():
            Logger.ERROR('Invalid MCP date range.')
            raise ToolError('Use an ordered range of at most 31 dates, without future dates.')
        return end_date

    def finish(records):
        failed = [r.get('status') == 'error' or r.get('warning') is not None or r.get('stale') for r in records]
        status = 'error' if all(r.get('status') == 'error' for r in records) else 'partial' if any(failed) else 'ok'
        result = dict(schema_version=1, status=status, records=records)
        if len(json.dumps(result, allow_nan=False).encode()) > 256 * 1024:
            return dict(schema_version=1, status='error', error='result_too_large',
                        message='Request fewer dates or a smaller activity page.')
        return result

    async def collect(dataset, start_date, end_date, cache_mode):
        if dataset in ('steps', 'stress') and (end_date - start_date).days >= 28:
            Logger.ERROR('Dataset date range exceeds endpoint limit.')
            raise ToolError('Steps and stress support at most 28 inclusive dates; split the request.')
        endpoint = DAILY.get(dataset) or RANGES.get(dataset)
        if dataset in DAILY:
            records = []
            for offset in range((end_date - start_date).days + 1):
                day = start_date + timedelta(days=offset)
                params = dict(calendar_date=day.isoformat())
                if dataset == 'fitness_age':
                    params['full_history_scan'] = True
                records.append(await store.read(endpoint, params, day.isoformat(), mode=cache_mode, dated_end=day))
            return records
        return [await store.read(endpoint, dict(start_date=start_date.isoformat(), end_date=end_date.isoformat(),
                       **({'include_all': False} if dataset == 'weight' else {})),
                       'ranges', mode=cache_mode, dated_end=end_date)]

    @server.tool(annotations={'readOnlyHint': True})
    async def get_garmin_data(dataset: Dataset, start_date: date, end_date: date | None = None,
                              cache_mode: CacheMode = 'prefer_local') -> dict:
        """Read up to 31 dates. Daily endpoints reuse each date; range endpoints cache exact ranges.

        Payloads preserve Garmin units and structure. Empty payloads are not proof of no data.
        local_only never accesses Garmin; refresh forces retrieval. Inspect per-record freshness.
        """
        end_date = dates(start_date, end_date)
        return finish(await collect(dataset, start_date, end_date, cache_mode))

    @server.tool(annotations={'readOnlyHint': True})
    async def get_garmin_day(calendar_date: date, datasets: list[Dataset],
                             cache_mode: CacheMode = 'prefer_local') -> dict:
        """Retrieve explicitly selected datasets for a date, retaining independent failures."""
        dates(calendar_date, calendar_date)
        if not datasets or len(datasets) > len(DAILY) + len(RANGES) or len(set(datasets)) != len(datasets):
            Logger.ERROR('Invalid daily dataset selection.')
            raise ToolError('Choose distinct datasets from the advertised list.')
        records = []
        for dataset in datasets:
            records.extend(await collect(dataset, calendar_date, calendar_date, cache_mode))
        return finish(records)

    @server.tool(annotations={'readOnlyHint': True})
    async def search_garmin_activities(start_date: date, end_date: date,
                                       activity_type: str = 'cycling', start: int = 0,
                                       limit: int = 20, cache_mode: CacheMode = 'prefer_local') -> dict:
        """Search one activity page over up to 31 dates. Pages are not complete inventories.

        Use start offsets to paginate; details are available by activity ID.
        """
        dates(start_date, end_date)
        if start < 0 or not 1 <= limit <= 99 or len(activity_type) > 80:
            Logger.ERROR('Invalid activity search arguments.')
            raise ToolError('Use start >= 0, limit 1..99 and a short activity type.')
        params = dict(start_date=start_date.isoformat(), end_date=end_date.isoformat(),
                      activity_type=activity_type, start=start, limit=limit, favorite=-1,
                      sort_order='desc', exclude_children=True)
        return finish([await store.read('search_activities', params, 'ranges', mode=cache_mode, dated_end=end_date)])

    @server.tool(annotations={'readOnlyHint': True})
    async def get_garmin_activity(activity_id: int, workouts: bool = False,
                                  cache_mode: CacheMode = 'prefer_local') -> dict:
        """Retrieve activity detail or its structured workout. No unsupported sample endpoints."""
        if activity_id <= 0:
            Logger.ERROR('Invalid activity identifier.')
            raise ToolError('Activity ID must be positive.')
        endpoint = 'get_activity_workouts' if workouts else 'get_activity'
        return finish([await store.read(endpoint, dict(activity_id=activity_id),
                                       f'activities/{activity_id}', mode=cache_mode)])

    @server.tool(annotations={'readOnlyHint': True})
    async def get_garmin_profile(dataset: Literal['settings', 'heart_rate_zones'] = 'settings',
                                 cache_mode: CacheMode = 'prefer_local') -> dict:
        """Read profile settings or heart-rate zones; settings use a 24-hour freshness period."""
        endpoint = 'get_user_profile_settings' if dataset == 'settings' else 'get_heart_rate_zones'
        params = {} if dataset == 'settings' else dict(generate_defaults=True)
        return finish([await store.read(endpoint, params, 'profile', mode=cache_mode)])

    @server.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def list_local_garmin_data(start_date: date, end_date: date,
                                     datasets: list[Dataset], cursor: int = 0, limit: int = 100) -> dict:
        """Inspect daily local availability only. Range datasets look up the exact requested range.

        This bounded listing probes known identities, never scans arbitrary files or fetches Garmin.
        """
        dates(start_date, end_date)
        if not datasets or len(set(datasets)) != len(datasets) or len(datasets) > 11 or cursor < 0 or not 1 <= limit <= 100:
            Logger.ERROR('Invalid local listing arguments.')
            raise ToolError('Use distinct datasets, a nonnegative cursor and limit 1..100.')
        records = []
        for dataset in datasets:
            records.extend(await collect(dataset, start_date, end_date, 'local_only'))
        page = records[cursor:cursor + limit]
        metadata = [{k: v for k, v in record.items() if k != 'data'} for record in page]
        return dict(schema_version=1, records=metadata,
                    next_cursor=cursor + limit if cursor + limit < len(records) else None)

    register_api_tools(server, store, finish, config.timezone_name)
    return server


def suppress_server_dependency_logs():
    """Silence FastMCP/Uvicorn in this server process without changing Daybreak logging."""
    prefixes = ('fastmcp', 'uvicorn')
    for prefix in prefixes:
        logging.getLogger(prefix)
    names = tuple(logging.Logger.manager.loggerDict)
    for name in names:
        if any(name == prefix or name.startswith(prefix + '.') for prefix in prefixes):
            dependency_logger = logging.getLogger(name)
            dependency_logger.handlers.clear()
            dependency_logger.addHandler(logging.NullHandler())
            dependency_logger.propagate = False
            dependency_logger.disabled = True


def main():
    """Load configuration and run one shared local service until shutdown."""
    root = Path(__file__).resolve().parents[1]
    config = GlobalConfig()
    config.update_from_toml(root / 'config/default_config.toml')
    config.update_from_cli()
    try:
        suppress_server_dependency_logs()
        Logger.INFO('Effective configuration:\n%s',
                    json.dumps(config.to_display_dict(), indent=2, ensure_ascii=False))
        server = create_server()
        settings = config.MCPServer
        if settings.transport == 'stdio':
            server.run(transport='stdio', show_banner=False)
        else:
            Logger.INFO('Starting local MCP HTTP service; host=%s; port=%d; path=%s.',
                        settings.host, settings.port, settings.path)
            server.run(transport='http', host=settings.host, port=settings.port,
                       path=settings.path, stateless_http=False,
                       host_origin_protection=True, show_banner=False,
                       uvicorn_config={'log_config': None, 'access_log': False})
    finally:
        Logger.close()


if __name__ == '__main__':
    main()
