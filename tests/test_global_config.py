"""Synthetic configuration precedence and validation checks."""

import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

import tomllib

from global_config import ConfigData, GlobalConfig, global_config


class GlobalConfigTests(unittest.TestCase):
    def setUp(self):
        self.saved = (global_config._toml, global_config._cli, global_config._data)
        global_config._toml = {}
        global_config._cli = {}
        global_config._data = ConfigData()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "settings.toml"

    def tearDown(self):
        global_config._toml, global_config._cli, global_config._data = self.saved
        self.directory.cleanup()

    def load(self, content):
        self.path.write_text(content, encoding="utf-8")
        global_config.update_from_toml(self.path)

    def test_default_toml_matches_schema_and_loads(self):
        path = Path(__file__).resolve().parents[1] / "config/default_config.toml"
        defaults = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(defaults), {"Logging", "MCPServer", "GeneralHttpClient", "GarminConnectClient"})
        base = ConfigData()
        # The checked-in TOML may deliberately enable diagnostic DEBUG output.
        self.assertIn(defaults['Logging']['level'], ('INFO', 'DEBUG'))
        self.assertIn(defaults['Logging']['console']['level'], ('INFO', 'DEBUG'))
        configured = replace(base, Logging=replace(
            base.Logging, level=defaults['Logging']['level'],
            console=replace(base.Logging.console, level=defaults['Logging']['console']['level'])))
        expected = asdict(configured)
        self.assertEqual(expected["GarminConnectClient"].pop("http_client_name"), "GarminConnect")
        self.assertEqual(defaults, expected)
        global_config.update_from_toml(path)
        self.assertEqual(global_config._data, configured)
        self.assertEqual(global_config.GarminConnectClient.http_client_pool_size, 10)

    def test_garmin_configuration_validation(self):
        self.load('[GarminConnectClient]\napi_key_string = "synthetic-key"\napi_key_file = "API_KEY.txt"\n')
        self.assertNotIn("synthetic-key", repr(global_config._data))
        global_config.update_from_cli(["--GarminConnectClient.http-client-pool-size", "4"])
        self.assertEqual(global_config.GarminConnectClient.http_client_pool_size, 4)
        for content in [
            'http_client_pool_size = 0',
            'http_client_pool_size = -1',
            'api_key_file = "/tmp/key"',
            'api_key_file = "../key"',
        ]:
            snapshot = global_config._data
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.load("[GarminConnectClient]\n" + content)
            self.assertIs(global_config._data, snapshot)

    def test_mcp_configuration_layers_and_validation(self):
        self.assertEqual(global_config.MCPServer.data_source, 'garmin_connect')
        self.load('[MCPServer]\ntimezone_name = "Asia/Shanghai"\nrecent_days = 4\n')
        global_config.update_from_cli(['--MCPServer.recent-days', '2',
                                       '--MCPServer.data-source', 'future_source'])
        self.assertEqual(global_config.MCPServer.recent_days, 2)
        self.assertEqual(global_config.MCPServer.timezone_name, 'Asia/Shanghai')
        self.assertEqual(global_config.MCPServer.data_source, 'future_source')
        global_config.update_from_cli([])
        for value in ['recent_ttl_seconds = 0', 'profile_ttl_seconds = 0',
                      'transport = "sse"', 'port = 0', 'port = 65536',
                      'host = "0.0.0.0"', 'host = "example.com"',
                      'path = "mcp"', 'path = "/../mcp"', 'path = "/mcp?key=x"',
                      'timezone_name = "not/a/timezone"', 'data_directory = " "',
                      'recent_days = -1', 'recent_days = true']:
            snapshot = global_config._data
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                self.load('[MCPServer]\n' + value)
            self.assertIs(global_config._data, snapshot)

    def test_display_configuration_masks_credentials_without_mutation(self):
        self.load('[GarminConnectClient]\napi_key_string = "synthetic-secret"\n')
        global_config.update_from_cli(['--MCPServer.timezone-name', 'Asia/Shanghai'])
        displayed = global_config.to_display_dict()
        self.assertEqual(list(displayed), ['MCPServer', 'GarminConnectClient', 'GeneralHttpClient', 'Logging'])
        self.assertEqual(displayed['GarminConnectClient']['api_key_string'], '********')
        self.assertNotIn('synthetic-secret', str(displayed))
        self.assertEqual(displayed['MCPServer']['timezone_name'], 'Asia/Shanghai')
        self.assertEqual(displayed['Logging']['file']['backup_count'], 3)
        self.assertEqual(global_config.GarminConnectClient.api_key_string, 'synthetic-secret')

    def test_import_creates_singleton_without_parsing_arguments(self):
        subprocess.run([sys.executable, "-c",
                        "import global_config as m; "
                        "assert m.GlobalConfig._instance is m.global_config; "
                        "assert m.GlobalConfig() is m.global_config",
                        "--unrelated-host-argument"], check=True)
        self.assertIs(GlobalConfig(), global_config)

    def test_partial_toml_and_cli_precedence_in_either_order(self):
        self.load("[GeneralHttpClient]\ntimeout = 12\nmax_connections = 50\n")
        self.assertEqual(global_config.GeneralHttpClient.timeout, 12.0)
        self.assertEqual(global_config.GeneralHttpClient.keepalive_expiry, 5.0)
        global_config.update_from_cli(["--GeneralHttpClient.timeout", "3"])
        self.assertEqual(global_config.GeneralHttpClient.timeout, 3.0)
        self.assertEqual(global_config.GeneralHttpClient.max_connections, 50)
        self.load("[GeneralHttpClient]\ntimeout = 20\n")
        self.assertEqual(global_config.GeneralHttpClient.timeout, 3.0)
        self.assertEqual(global_config.GeneralHttpClient.max_connections, 100)
        global_config.update_from_cli([])
        self.assertEqual(global_config.GeneralHttpClient.timeout, 20.0)

    def test_empty_toml_and_invalid_updates_are_atomic(self):
        self.load("")
        self.assertEqual(global_config.GeneralHttpClient.timeout, 5.0)
        cases = [
            ("[]", tomllib.TOMLDecodeError),
            ('GeneralHttpClient = "invalid"', TypeError),
            ("unknown = 1", ValueError),
            ("[GeneralHttpClient]\ntimeout = true", TypeError),
            ("[GeneralHttpClient]\ntimeout = -1", ValueError),
            ("[GeneralHttpClient]\nmax_connections = 1.5", TypeError),
            ("[GeneralHttpClient", tomllib.TOMLDecodeError),
            ("[GeneralHttpClient]\ntimeout = 1\ntimeout = 2", tomllib.TOMLDecodeError),
        ]
        for content, error in cases:
            snapshot = global_config._data
            with self.subTest(content=content), self.assertRaises(error):
                self.load(content)
            self.assertIs(global_config._data, snapshot)

    def test_cli_validation_and_hyphenated_names(self):
        global_config.update_from_cli(["--GeneralHttpClient.max-connections", "10"])
        self.assertEqual(global_config.GeneralHttpClient.max_connections, 10)
        with self.assertRaises(ValueError):
            global_config.update_from_cli(["--GeneralHttpClient.max-connections", "0"])
        self.assertEqual(global_config.GeneralHttpClient.max_connections, 10)

    def test_logging_nested_overrides_and_boolean_cli(self):
        self.load('[Logging]\nlevel = "DEBUG"\n[Logging.file]\npath = "logs/test.log"\n')
        self.assertEqual(global_config.Logging.level, "DEBUG")
        self.assertTrue(global_config.Logging.console.enabled)
        self.assertFalse(global_config.Logging.file.enabled)
        global_config.update_from_cli([
            "--Logging.file.enabled", "--no-Logging.console.enabled",
            "--Logging.file.max-bytes", "2048",
        ])
        self.assertTrue(global_config.Logging.file.enabled)
        self.assertFalse(global_config.Logging.console.enabled)
        self.assertEqual(global_config.Logging.file.path, "logs/test.log")
        self.assertEqual(global_config.Logging.file.max_bytes, 2048)
        self.load('[Logging.file]\nenabled = false\n')
        self.assertTrue(global_config.Logging.file.enabled)
        global_config.update_from_cli([])
        self.assertFalse(global_config.Logging.file.enabled)

    def test_invalid_logging_updates_are_atomic(self):
        for content, error in [
            ('[Logging]\nlevel = "INVALID"', ValueError),
            ('[Logging.console]\nenabled = "false"', TypeError),
            ('[Logging.file]\npath = " "', ValueError),
            ('[Logging.file]\nmax_bytes = 0', ValueError),
            ('[Logging.file]\nbackup_count = -1', ValueError),
        ]:
            snapshot = global_config._data
            with self.subTest(content=content), self.assertRaises(error):
                self.load(content)
            self.assertIs(global_config._data, snapshot)


if __name__ == "__main__":
    unittest.main()
