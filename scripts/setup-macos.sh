#!/bin/bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ]; then
  echo 'This setup is for macOS.' >&2
  exit 1
fi
for tool in python3 node npm git swiftc; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Install Python 3.12+, Node 22.12+, Xcode Command Line Tools." >&2; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 12)) process.exit(1)'
mkdir -p .state .vendor
chmod 700 .state
if [ ! -d .vendor/siwc ]; then
  git clone https://github.com/openai/sign-in-with-chatgpt-devkit.git .vendor/siwc
fi
git -C .vendor/siwc checkout --detach 0a36fefeb913055c8c7a1a29b63d82b96b2e841a
(cd .vendor/siwc && npm ci && npm run build --workspace @siwc/local)
swiftc integrations/chatgpt/keychain.swift -o .state/keychain-crypto
chmod 700 .state/keychain-crypto
python3 -m gateway.app init
echo 'ChatGPT adapter installed. Install official Grok Build and Antigravity CLI (agy) separately; see docs/ANTIGRAVITY.md.'
