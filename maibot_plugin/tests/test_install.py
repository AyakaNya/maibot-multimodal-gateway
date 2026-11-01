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
