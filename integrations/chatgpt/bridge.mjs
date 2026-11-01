// Trusted local adapter; never exports credentials over HTTP or stdout.
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

process.umask(0o077);
const root = fileURLToPath(new URL('../../', import.meta.url));
const helper = resolve(root, '.state/keychain-crypto');
const storageDir = resolve(root, '.state/chatgpt');

export async function execute(client, command, request = {}) {
  if (command === 'login') {
    const session = await client.signIn();
    return { status: session.status, sharing: session.sharing };
  }
  const session = await client.getSession();
  if (command === 'status') return { status: session.status, sharing: session.sharing };
  if (command === 'logout') { await client.disconnect(); return { status: 'disconnected' }; }
  if (!session.sharing) throw new Error('chatgpt_plan_permission_required');
  if (command === 'models') return { models: await client.listModels() };
  if (command !== 'text') throw new Error('unsupported_command');
  const models = await client.listModels();
  const selectedModel = request.model === 'default' ? models[0]?.slug : request.model;
  if (!models.some(model => model.slug === selectedModel)) throw new Error('model_not_available');
  const input = request.messages.map(message => ({
    role: message.role === 'system' ? 'developer' : message.role, content: message.content,
  }));
  const result = await client.streamResponse({ model: selectedModel, input, signal: AbortSignal.timeout(120000) });
  return { text: result.text };
}

async function main() {
  if (process.platform !== 'darwin') throw new Error('macos_required');
  mkdirSync(storageDir, { recursive: true, mode: 0o700 });
  const { createChatGPT } = await import('../../.vendor/siwc/packages/local/dist/index.js');
  const crypt = (op, input) => execFileSync(helper, [op], { input, maxBuffer: 4 * 1024 * 1024 });
  const client = createChatGPT({
    appName: 'MaiBot Multimodal Gateway', appId: 'maibot-multimodal-gateway',
    redirectPort: 0, storageDir, sendHostId: true,
    openBrowser: url => { execFileSync('/usr/bin/open', [url]); },
    credentialEncryption: {
      id: 'maibot-macos-keychain-aesgcm-v1', isAvailable: () => true,
      encrypt: plaintext => crypt('encrypt', Buffer.from(plaintext)),
      decrypt: ciphertext => crypt('decrypt', Buffer.from(ciphertext)).toString('utf8'),
    },
  });
  let request = {};
  if (process.argv[2] === 'text') {
    let input = '';
    for await (const chunk of process.stdin) {
      input += chunk;
      if (Buffer.byteLength(input) > 1024 * 1024) throw new Error('input_limit');
    }
    request = JSON.parse(input);
  }
  console.log(JSON.stringify(await execute(client, process.argv[2], request)));
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => { console.error('ChatGPT operation failed. Check setup, local sign-in, granted plan permission, and model availability.'); process.exitCode = 1; });
}
