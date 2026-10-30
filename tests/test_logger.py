"""Synthetic checks for logger routing, lifecycle, and rotation."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from global_config import ConfigData, global_config
from logger import Logger


class LoggerTests(unittest.TestCase):
    def setUp(self):
        Logger.close()
        self.saved = (global_config._toml, global_config._cli, global_config._data)
        global_config._toml = {}
        global_config._cli = {}
        global_config._data = ConfigData()

    def tearDown(self):
        Logger.close()
        global_config._toml, global_config._cli, global_config._data = self.saved

    def test_singleton_concurrent_initialization(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            instances = list(executor.map(lambda _: Logger(), range(32)))
        self.assertTrue(all(item is instances[0] for item in instances))
        self.assertEqual(len(instances[0]._logger.handlers), 2)

    def test_console_levels_formatting_and_exception(self):
        stderr, stdout = StringIO(), StringIO()
        with redirect_stderr(stderr), redirect_stdout(stdout):
            Logger.DEBUG("hidden debug")
            Logger.INFO("synthetic %s", "message")
            try:
                raise ValueError("synthetic failure")
            except ValueError:
                Logger.ERROR("request failed", exc_info=True)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("hidden debug", stderr.getvalue())
        self.assertEqual(stderr.getvalue().count("INFO daybreak: synthetic message"), 1)
        self.assertIn("ValueError: synthetic failure", stderr.getvalue())

    def test_all_outputs_disabled_are_silent(self):
        global_config.update_from_cli(["--no-Logging.console.enabled"])
        output = StringIO()
        with redirect_stderr(output):
            Logger.ERROR("silent error")
        self.assertEqual(output.getvalue(), "")

    def test_independent_handler_levels_and_shared_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "synthetic.log"
            global_config.update_from_cli([
                "--Logging.level", "DEBUG", "--Logging.console.level", "ERROR",
                "--Logging.file.enabled", "--Logging.file.level", "DEBUG",
                "--Logging.file.path", str(path),
            ])
            output = StringIO()
            with redirect_stderr(output):
                Logger.DEBUG("file debug")
                Logger.INFO("file info")
                Logger.ERROR("both error")
            Logger.close()
            content = path.read_text(encoding="utf-8")
            self.assertIn("file debug", content)
            self.assertIn("file info", content)
            self.assertIn("both error", output.getvalue())
            self.assertNotIn("file info", output.getvalue())
            global_config.update_from_cli([
                "--Logging.level", "ERROR", "--Logging.console.level", "DEBUG",
            ])
            output = StringIO()
            with redirect_stderr(output):
                Logger.INFO("filtered by shared level")
            self.assertEqual(output.getvalue(), "")

    def test_file_rotation_and_close_reinitialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.log"
            global_config.update_from_cli([
                "--no-Logging.console.enabled", "--Logging.file.enabled",
                "--Logging.file.path", str(path), "--Logging.file.max-bytes", "120",
                "--Logging.file.backup-count", "2",
            ])
            first = Logger()
            for index in range(10):
                Logger.INFO("synthetic record %s %s", index, "x" * 40)
            handler = first._logger.handlers[0]
            Logger.close()
            self.assertIsNone(handler.stream)
            self.assertTrue(path.with_name(path.name + ".1").exists())
            self.assertTrue(path.with_name(path.name + ".2").exists())
            self.assertFalse(path.with_name(path.name + ".3").exists())
            self.assertIsNot(first, Logger())
            Logger.close()


if __name__ == "__main__":
    unittest.main()
