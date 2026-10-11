"""Browser-script behavior checks without a browser dependency."""

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend behavior checks")
class FinalizationFrontendTests(unittest.TestCase):
    def run_node(self, script):
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_chat_end_modal_pending_conflict_success_and_stale_chat(self):
        self.run_node(r"""
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const vm = require('node:vm');
            const html = fs.readFileSync('frontend/index.html', 'utf8');
            assert.match(html, /id="endSessionBtn"/);
            assert.match(html, /id="endSessionDialog"[^>]*aria-modal="true"/);
            assert.match(html, /href="\/analytics.html"/);
            assert.match(html, /id="sidebarNewChatBtn"/);
            const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];
            const nodes = new Map();
            let document;
            function node(tag = 'div') {
                const classes = new Set();
                const item = {
                    tagName: tag, children: [], style: {}, attributes: {}, hidden: false,
                    disabled: false, isConnected: true, value: '', innerText: '',
                    classList: { add: (...names) => names.forEach(name => classes.add(name)),
                        remove: (...names) => names.forEach(name => classes.delete(name)),
                        contains: name => classes.has(name) },
                    appendChild(child) { this.children.push(child); return child; },
                    append(...children) { children.forEach(child => this.appendChild(child)); },
                    setAttribute(key, value) { this.attributes[key] = value; },
                    removeAttribute(key) { delete this.attributes[key]; },
                    addEventListener(key, callback) { (this.events ||= {})[key] = callback; },
                    focus() { document.activeElement = this; },
                    remove() { this.isConnected = false; },
                    contains() { return false; }
                };
                Object.defineProperty(item, 'innerHTML', {
                    get() { return this.html || ''; },
                    set(value) { this.html = value; this.children = []; }
                });
                return item;
            }
            document = {
                activeElement: null, events: {},
                getElementById(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
                createElement: node,
                querySelectorAll() { return []; },
                addEventListener(key, callback) { (this.events[key] ||= []).push(callback); }
            };
            document.getElementById('endSessionDialog').hidden = true;
            const storage = new Map([['username', 'Tester'], ['user_id', 'owner'], ['trace_session_owner', 'one']]);
            const localStorage = { getItem: key => storage.get(key) || null,
                setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
            const calls = [];
            let pendingId = null;
            let endConflict = false;
            let delayEnd = false;
            let endResolver = null;
            let delayHistoryForTwo = false;
            let historyTwoResolver = null;
            let twoActive = false;
            const delayedChats = new Map();
            const reply = (status, data) => ({ ok: status < 400, status, json: async () => data });
            const sessions = () => [{ session_id: 'one', status: 'active', message_count: 1 },
                { session_id: 'two', status: twoActive ? 'active' : 'ended', message_count: 1 }];
            async function fetch(url, options = {}) {
                calls.push({ url, options });
                if (url === '/sessions/user/owner') return reply(200, { success: true, sessions: sessions() });
                if (url.includes('/messages')) {
                    const id = url.split('/')[2];
                    if (id === 'two' && delayHistoryForTwo)
                        return new Promise(resolve => { historyTwoResolver = resolve; });
                    return reply(200, { session_id: id, status: id === 'one' || twoActive ? 'active' : 'ended',
                        message_count: 1, pending_interaction_id: id === 'one' ? pendingId : null,
                        messages: [{ user_message: 'hello', llama_response: 'world' }] });
                }
                if (url.endsWith('/end')) {
                    if (endConflict) return reply(409, { detail: { message: 'All interaction feedback must be submitted', interaction_id: 'older-reply', pending_feedback_count: 1 } });
                    if (delayEnd) return new Promise(resolve => { endResolver = resolve; });
                    return reply(200, { success: true, session: { session_id: 'one', status: 'ended' },
                        finalization: { is_finalized: true } });
                }
                if (url === '/chat') {
                    const id = JSON.parse(options.body).session_id;
                    return new Promise(resolve => { delayedChats.set(id, resolve); });
                }
                throw new Error(`Unexpected ${url}`);
            }
            const context = vm.createContext({ document, localStorage, fetch, window: { location: {} },
                setInterval() {}, setTimeout() {}, URL, console });
            vm.runInContext(code, context);
            const run = source => vm.runInContext(source, context);
            const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
            (async () => {
                await tick();
                const el = id => document.getElementById(id);
                assert.equal(el('endSessionBtn').disabled, false);
                assert.equal(el('msg').disabled, false);
                const initialHistory = el('chatBox').children.length;
                run('openEndSessionDialog()');
                assert.equal(el('endSessionDialog').hidden, false);
                assert.equal(document.activeElement, el('cancelEndSessionBtn'));
                run('closeEndSessionDialog()');
                assert.equal(el('endSessionDialog').hidden, true);
                run('openSessionSidebar()');
                run('openEndSessionDialog()');
                const escape = { key: 'Escape', preventDefault() {} };
                document.events.keydown.forEach(handler => handler(escape));
                assert.equal(el('endSessionDialog').hidden, true);
                assert.equal(el('sessionSidebar').classList.contains('open'), true);
                run('requireFeedback("reply-one")');
                assert.equal(el('endSessionBtn').disabled, true);
                run('openEndSessionDialog()');
                assert.equal(el('endSessionDialog').hidden, true);
                assert.equal(calls.filter(call => call.url.endsWith('/end')).length, 0);
                run('clearFeedbackState(true)');
                endConflict = true;
                run('openEndSessionDialog()');
                await run('confirmEndSession()');
                assert.match(el('toastMessage').innerText, /feedback/i);
                assert.equal(el('endSessionBtn').disabled, true);
                assert.equal(el('feedbackPanel').style.display, 'block');
                assert.equal(run('lastInteractionId'), 'older-reply');
                run('clearFeedbackState(true)');
                run('openEndSessionDialog()');
                const endCount = calls.filter(call => call.url.endsWith('/end')).length;
                await run('switchSession("two")');
                assert.equal(el('endSessionDialog').hidden, true);
                await run('confirmEndSession()');
                assert.equal(calls.filter(call => call.url.endsWith('/end')).length, endCount);
                await run('switchSession("one")');
                twoActive = true;
                el('msg').value = 'from one';
                const firstChat = run('sendMsg()');
                await run('switchSession("two")');
                el('msg').value = 'from two';
                const secondChat = run('sendMsg()');
                await run('switchSession("one")');
                assert.equal(el('msg').disabled, true);
                assert.equal(el('endSessionBtn').disabled, true);
                el('msg').value = 'duplicate';
                await run('sendMsg()');
                assert.equal(calls.filter(call => call.url === '/chat').length, 2);
                delayedChats.get('one')(reply(503, { detail: 'Unavailable' }));
                await firstChat;
                assert.equal(el('msg').disabled, false);
                assert.equal(el('endSessionBtn').disabled, false);
                await run('switchSession("two")');
                assert.equal(el('msg').disabled, true);
                assert.equal(el('endSessionBtn').disabled, true);
                delayedChats.get('two')(reply(503, { detail: 'Unavailable' }));
                await secondChat;
                assert.equal(el('msg').disabled, false);
                twoActive = false;
                await run('switchSession("one")');
                el('msg').value = 'stale reply';
                const staleChat = run('sendMsg()');
                await run('switchSession("two")');
                delayedChats.get('one')(reply(200, { session_id: 'one', interaction_id: 'stale', llama_response: 'late' }));
                await staleChat;
                assert.equal(el('feedbackPanel').style.display, 'none');
                assert.equal(el('msg').disabled, true);
                await run('switchSession("one")');
                endConflict = false;
                delayEnd = true;
                run('openEndSessionDialog()');
                const ending = run('confirmEndSession()');
                const oneHistoryCount = calls.filter(call => call.url.includes('/sessions/one/messages')).length;
                delayHistoryForTwo = true;
                const pendingB = run('switchSession("two")');
                assert.equal(el('endSessionBtn').disabled, true);
                assert.equal(el('msg').disabled, true);
                endResolver(reply(200, { success: true, session: { session_id: 'one', status: 'ended' },
                    finalization: { is_finalized: true } }));
                await ending;
                assert.equal(calls.filter(call => call.url.includes('/sessions/one/messages')).length, oneHistoryCount);
                historyTwoResolver(reply(200, { session_id: 'two', status: 'ended', message_count: 1,
                    pending_interaction_id: null, messages: [{ user_message: 'other', llama_response: 'reply' }] }));
                await pendingB;
                assert.equal(run('sessionId'), 'two');
                assert.equal(el('msg').disabled, true);
                delayHistoryForTwo = false;
                await run('switchSession("one")');
                assert.match(el('sessionStatus').innerText, /ended/i);
                assert.match(el('sessionStatus').innerText, /Final analytics saved/);
                assert.equal(el('msg').disabled, true);
                assert.equal(el('sendBtn').disabled, true);
                assert.equal(el('feedbackPanel').style.display, 'none');
                assert.equal(el('endSessionBtn').hidden, true);
                assert.equal(el('chatBox').children.length, initialHistory);
                assert.equal(el('sidebarNewChatBtn').disabled, false);
                el('msg').value = 'should not send';
                await run('sendMsg()');
                assert.equal(calls.filter(call => call.url === '/chat').length, 3);
            })().catch(error => { console.error(error); process.exitCode = 1; });
        """)

    def test_analytics_finalized_active_and_legacy_labels(self):
        self.run_node(r"""
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const html = fs.readFileSync('frontend/analytics.html', 'utf8');
            assert.match(html, /id="finalizationStatus"/);
            const api = require('./frontend/analytics.js');
            const final = api.finalizationPresentation(
                { is_finalized: true, finalized_at: '2026-10-10T12:00:00Z', analytics_version: 1 },
                { status: 'ended' });
            assert.equal(final.label, 'Finalized');
            assert.match(final.date, /Finalized/);
            assert.equal(final.finalized, true);
            assert.equal(api.finalizationPresentation(null, { status: 'active' }).label, 'Active');
            const legacy = api.finalizationPresentation(null, { status: 'ended' });
            assert.equal(legacy.label, 'Ended');
            assert.equal(legacy.finalized, false);
            assert.equal(legacy.date, '');
        """)


if __name__ == "__main__":
    unittest.main()
