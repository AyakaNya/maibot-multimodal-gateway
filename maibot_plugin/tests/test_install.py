import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bridge_installer', ROOT / 'scripts/install-maibot-plugin.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / 'bot.py').write_text('# untouched core\n')
        (self.root / 'pyproject.toml').write_text('[project]\nversion="1.3.19"\n')

    def test_install_preserves_credentials_and_update_preserves_config(self):
        key = self.root / 'local.key'
        key.write_text('dummy-secret-never-copy-this')
        target = installer.install(self.root, gateway_key_file=key)
        config = target / 'config.toml'
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed['gateway']['key_file'], str(key))
        self.assertFalse(parsed['plugin']['enabled'])
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        for path in target.iterdir():
            if path.is_file():
                self.assertNotIn(key.read_bytes(), path.read_bytes())
        config.write_text(config.read_text().replace('cooldown_seconds = 5.0', 'cooldown_seconds = 19.0'))
        saved = config.read_bytes()
        with self.assertRaises(ValueError):
            installer.install(self.root)
        installer.install(self.root, update=True)
        self.assertEqual(config.read_bytes(), saved)
        self.assertEqual((self.root / 'bot.py').read_text(), '# untouched core\n')
        self.assertEqual(key.read_text(), 'dummy-secret-never-copy-this')

    def test_reject_unsupported_host_before_install(self):
        (self.root / 'pyproject.toml').write_text('[project]\nversion="1.2.0"\n')
        with self.assertRaises(ValueError):
            installer.install(self.root)
        self.assertFalse((self.root / 'plugins').exists())

    def test_reject_symlink_destination_without_writing(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (self.root / 'plugins').symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            installer.install(self.root)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_instance_without_source_installs_only_plugin_and_preserves_state(self):
        (self.root / 'bot.py').unlink()
        (self.root / 'pyproject.toml').unlink()
        for name in ('config', 'data', 'plugins'):
            (self.root / name).mkdir()
        marker = self.root / 'config/bot_config.toml'
        marker.write_text('existing-settings')
        nested = self.root / 'my-maibot'
        nested.mkdir()
        (nested / 'do-not-touch').write_text('existing-runtime')
        target = installer.install(self.root, instance_mode=True, host_version='1.3.19')
        self.assertEqual(target.parent, self.root / 'plugins')
        self.assertTrue((target / 'plugin.py').is_file())
        self.assertEqual(marker.read_text(), 'existing-settings')
        self.assertEqual((nested / 'do-not-touch').read_text(), 'existing-runtime')
        self.assertFalse((self.root / 'bot.py').exists())

    def test_instance_requires_explicit_supported_version_and_directory_layout(self):
        for name in ('config', 'data', 'plugins'):
            (self.root / name).mkdir()
        for version in (None, '1.2.0', 'latest', '1.3.19.1'):
            with self.assertRaises(ValueError):
                installer.install(self.root, instance_mode=True, host_version=version)
        (self.root / 'config').rmdir()
        with self.assertRaises(ValueError):
            installer.install(self.root, instance_mode=True, host_version='1.3.19')
        self.assertEqual(list((self.root / 'plugins').iterdir()), [])

    def test_1318_source_and_instance_install_and_below_minimum_rejection(self):
        (self.root / 'pyproject.toml').write_text('[project]\nversion="1.3.18"\n')
        target = installer.install(self.root)
        original = (target / 'config.toml').read_bytes()
        for name in ('config', 'data'):
            (self.root / name).mkdir()
        installer.install(self.root, instance_mode=True, host_version='1.3.18', update=True)
        self.assertEqual((target / 'config.toml').read_bytes(), original)
        for mode in (False, True):
            (self.root / 'pyproject.toml').write_text('[project]\nversion="1.3.17"\n')
            with self.assertRaises(ValueError):
                installer.install(self.root, instance_mode=mode, host_version='1.3.17', update=True)
        self.assertEqual((target / 'config.toml').read_bytes(), original)
