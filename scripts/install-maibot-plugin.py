"""Install only the bridge plugin files; never modify MaiBot core or credentials."""
import argparse
import json
from pathlib import Path
import shutil
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'maibot_plugin/maibot_multimodal_gateway'
FILES = ('__init__.py', 'plugin.py', 'client.py', '_manifest.json', 'config.example.toml',
         'requirements.txt', '.gitignore', 'README.md', 'LICENSE')


def install(maibot_dir, *, update=False, gateway_key_file=None):
    maibot_dir = Path(maibot_dir).expanduser().resolve()
    if not (maibot_dir / 'bot.py').is_file():
        raise ValueError('目標必須是包含 bot.py 的 MaiBot 專案目錄')
    try:
        project = tomllib.loads((maibot_dir / 'pyproject.toml').read_text())['project']
        version = str(project['version'])
        numbers = tuple(map(int, version.split('.')))
    except (OSError, ValueError, KeyError):
        raise ValueError('無法確認 MaiBot 版本；本版支援 MaiBot 1.3.19–1.3.99') from None
    if len(numbers) != 3 or not (1, 3, 19) <= numbers <= (1, 3, 99):
        raise ValueError('本插件目標為 MaiBot 1.3.19–1.3.99；不修改或升級 MaiBot 核心')
    plugins = maibot_dir / 'plugins'
    target = plugins / 'maibot_multimodal_gateway'
    if plugins.is_symlink() or target.is_symlink():
        raise ValueError('插件目錄不能是符號連結')
    if target.exists() and not update:
        raise ValueError('插件已存在；更新請加 --update，會保留 config.toml')
    # Verify the bundle before touching the destination.
    if any(not (SOURCE / name).is_file() or (SOURCE / name).is_symlink() for name in FILES):
        raise ValueError('插件安裝檔案不完整')
    if any((target / name).is_symlink() for name in (*FILES, 'config.toml')):
        raise ValueError('目的插件檔案不能是符號連結')
    key = None
    if gateway_key_file is not None:
        key_path = Path(gateway_key_file).expanduser().absolute()
        if not key_path.is_file() or key_path.is_symlink():
            raise ValueError('Gateway key 檔案不存在或是符號連結')
        key = str(key_path)  # Store only its path, never read/copy the secret.
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in FILES:
        destination = target / name
        if destination.is_symlink():
            raise ValueError('目的插件檔案不能是符號連結')
        shutil.copyfile(SOURCE / name, destination)
    config = target / 'config.toml'
    if not config.exists() and not config.is_symlink():
        content = (SOURCE / 'config.example.toml').read_text()
        if key is not None:
            content = content.replace('key_file = ""', 'key_file = ' + json.dumps(key, ensure_ascii=False))
        with config.open('x') as output:
            output.write(content)
        config.chmod(0o600)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maibot-dir', required=True, type=Path)
    parser.add_argument('--gateway-key-file', type=Path)
    parser.add_argument('--update', action='store_true')
    args = parser.parse_args()
    try:
        target = install(args.maibot_dir, update=args.update, gateway_key_file=args.gateway_key_file)
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
    print(f'Installed plugin: {target}')
    print('No credentials copied. Start/reload the MaiBot plugin, configure the allowed Mai Chat stream, then enable it.')


if __name__ == '__main__':
    main()
