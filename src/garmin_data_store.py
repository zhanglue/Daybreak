"""Local-first JSON persistence; one writer process per account store."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from typing import Literal
from zoneinfo import ZoneInfo
from zipfile import is_zipfile

from async_http_client import HttpClientError
from global_config import MCPServerConfig
from logger import Logger

CacheMode = Literal['prefer_local', 'local_only', 'refresh']


class GarminDataStore:
    _root: Path
    _policy: MCPServerConfig
    _locks: dict
    _client: object
    _versions: dict
    _factory: object
    _clock: object

    async def read(self, endpoint, parameters, folder, *, mode='prefer_local', dated_end=None,
                   cache_context=None):
        """Read an exact identity, fetching only when required. None is unavailable."""
        if mode not in ('prefer_local', 'local_only', 'refresh'):
            Logger.ERROR('Invalid cache mode.')
            raise ValueError('Invalid cache mode.')
        identity = dict(schema_version=1, endpoint=endpoint, parameters=parameters,
                        calendar_timezone=self._policy.timezone_name)
        if cache_context is not None:
            identity['cache_context'] = cache_context
        digest = hashlib.sha256(GarminDataStore._encode(identity)).hexdigest()
        path = self._root / folder / f'{endpoint}--{digest}.json'
        lock = self._locks.setdefault(digest, asyncio.Lock())
        version = self._versions.get(digest, 0)
        async with lock:
            try:
                self._check_path(path)
            except ValueError:
                return dict(**identity, status='error', source=None, fetched_at=None,
                            stale=False, persisted=False, error='unsafe_local_path')
            record = self._load(path, identity)
            stale = record is not None and self._stale(record, dated_end)
            refreshed_while_waiting = self._versions.get(digest, 0) != version
            if record and (mode != 'refresh' or refreshed_while_waiting) and (mode == 'local_only' or not stale):
                return dict(**record, source='local', stale=stale, persisted=True)
            if mode == 'local_only':
                return dict(**identity, status='error', source=None, fetched_at=None,
                            stale=False, persisted=False, error='local_miss')
            try:
                if self._client is None:
                    self._client = await self._factory()
                data = await getattr(self._client, endpoint)(**parameters)
            except (HttpClientError, ValueError, OSError):
                Logger.ERROR('Garmin data acquisition failed.')
                data = None
            archive = data if endpoint == 'download_activity' else None
            if endpoint == 'download_activity' and data is not None:
                if not isinstance(data, bytes) or not is_zipfile(BytesIO(data)):
                    Logger.ERROR('Garmin activity archive is not a valid ZIP.')
                    data = None
                else:
                    archive_digest = hashlib.sha256(data).hexdigest()
                    data = dict(media_type='application/zip', size_bytes=len(data), sha256=archive_digest,
                                resource_uri=f"daybreak://activities/{parameters['activity_id']}/{archive_digest}")
            if data is None:
                if record:
                    return dict(**record, source='local', stale=True, persisted=True,
                                warning='remote_unavailable')
                return dict(**identity, status='error', source=None, fetched_at=None,
                            stale=False, persisted=False, error='remote_unavailable')
            result = dict(**identity, status='ok', fetched_at=self._clock().isoformat(), data=data)
            try:
                if archive is not None:
                    archive_path = self._archive_path(parameters['activity_id'], data['sha256'])
                    self._write_bytes(archive_path, archive)
                self._write(path, result)
            except (OSError, ValueError, TypeError):
                Logger.ERROR('Local data persistence failed.')
                if archive is not None:
                    result['data'] = dict(data, resource_uri=None)
                return dict(**result, source='remote', stale=False, persisted=False,
                            warning='persistence_failed')
            self._versions[digest] = self._versions.get(digest, 0) + 1
            return dict(**result, source='remote', stale=False, persisted=True)

    def read_archive(self, activity_id, sha256) -> bytes:
        """Read a validated, content-addressed local ZIP through an MCP resource."""
        path = self._archive_path(activity_id, sha256)
        self._check_path(path)
        try:
            content = path.read_bytes()
        except OSError:
            Logger.ERROR('Local activity archive is unavailable.')
            raise ValueError('Local activity archive is unavailable.') from None
        if hashlib.sha256(content).hexdigest() != sha256:
            Logger.ERROR('Local activity archive checksum mismatch.')
            raise ValueError('Local activity archive checksum mismatch.')
        return content

    async def aclose(self):
        """Close only a client acquired by this service."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def __init__(self, root, policy: MCPServerConfig, *, client_factory,
                 clock=lambda: datetime.now(timezone.utc)):
        self._root = Path(root).absolute()
        self._policy = policy
        self._factory = client_factory
        self._clock = clock
        self._locks = {}
        self._versions = {}
        self._client = None

    def _check_path(self, path):
        if self._root.is_symlink() or any(p.is_symlink() for p in path.parents if p != self._root.parent):
            Logger.ERROR('Unsafe local store path.')
            raise ValueError('Unsafe local store path.')
        if path.is_symlink() or not path.resolve().is_relative_to(self._root.resolve()):
            Logger.ERROR('Unsafe local store path.')
            raise ValueError('Unsafe local store path.')

    def _load(self, path, identity):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(record, dict) or any(record.get(k) != v for k, v in identity.items())
                    or set(record) != set(identity) | {'status', 'fetched_at', 'data'}
                    or record.get('status') != 'ok' or record.get('data') is None):
                return None
            fetched = datetime.fromisoformat(record['fetched_at'])
            if fetched.tzinfo is None or fetched > self._clock():
                return None
            if identity['endpoint'] == 'download_activity':
                content = self.read_archive(identity['parameters']['activity_id'], record['data']['sha256'])
                expected_uri = f"daybreak://activities/{identity['parameters']['activity_id']}/{record['data']['sha256']}"
                if (len(content) != record['data'].get('size_bytes') or
                        record['data'].get('resource_uri') != expected_uri or
                        record['data'].get('media_type') != 'application/zip'):
                    return None
            return record
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            Logger.ERROR('Local data record could not be read.')
            return None

    def _stale(self, record, dated_end):
        now = self._clock()
        age = now - datetime.fromisoformat(record['fetched_at'])
        if dated_end is not None:
            cutoff = now.astimezone(ZoneInfo(self._policy.timezone_name)).date() - timedelta(days=self._policy.recent_days)
            if dated_end < cutoff and record['data'] not in ([], {}):
                return False
            ttl = self._policy.recent_ttl_seconds
        else:
            ttl = self._policy.profile_ttl_seconds if record['endpoint'] in (
                'get_user_profile_settings', 'get_heart_rate_zones') else self._policy.recent_ttl_seconds
        return age >= timedelta(seconds=ttl)

    def _write(self, path, record):
        encoded = GarminDataStore._encode(record)
        self._write_bytes(path, encoded)

    def _archive_path(self, activity_id, sha256):
        if (not str(activity_id).isascii() or not str(activity_id).isdigit() or int(activity_id) <= 0
                or not isinstance(sha256, str) or len(sha256) != 64
                or any(character not in '0123456789abcdef' for character in sha256)):
            Logger.ERROR('Invalid activity archive identity.')
            raise ValueError('Invalid activity archive identity.')
        return self._root / 'activities' / str(int(activity_id)) / f'download_activity--{sha256}.zip'

    def _write_bytes(self, path, encoded):
        self._check_path(path)
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._root.chmod(0o700)
        current = self._root
        for part in path.parent.relative_to(self._root).parts:
            current = current / part
            current.mkdir(exist_ok=True, mode=0o700)
            current.chmod(0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self._check_path(path)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _encode(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
