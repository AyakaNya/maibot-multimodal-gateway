import test from 'node:test';
import assert from 'node:assert/strict';
import { execute } from '../integrations/chatgpt/bridge.mjs';

test('identity login cannot invoke inference without plan permission', async () => {
  const client = { getSession: async () => ({ status: 'connected', sharing: false }) };
  await assert.rejects(execute(client, 'text'), /chatgpt_plan_permission_required/);
});
test('available model is checked and system maps to developer', async () => {
  let sent;
  const client = {
    getSession: async () => ({ sharing: true }), listModels: async () => [{ slug: 'allowed' }],
    streamResponse: async input => { sent = input; return { text: 'hello' }; },
  };
  assert.deepEqual(await execute(client, 'text', { model: 'allowed', messages: [{ role: 'system', content: 'instruction' }] }), { text: 'hello' });
  assert.equal(sent.input[0].role, 'developer');
  await assert.rejects(execute(client, 'text', { model: 'not-allowed', messages: [] }), /model_not_available/);
});
test('login output contains no credential fields', async () => {
  const result = await execute({ signIn: async () => ({ status: 'connected', sharing: true, credentials: 'secret' }) }, 'login');
  assert.deepEqual(result, { status: 'connected', sharing: true });
});
