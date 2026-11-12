'use strict';
// Sends a voice note through the WhatsApp Web page that OpenWA already keeps open in its (headless) Chromium. This OpenWA
// build cannot send files itself, so we use WhatsApp Web's own attachment pipeline from inside that page.
//   node wa_voice.js <openwa-home> check            -> {"ok":true}
//   node wa_voice.js <openwa-home> send   (stdin: {"chatId": "...", "b64": "<ogg opus>"}) -> {"ok":true,"id":"..."}
// Nothing is shown on screen: the browser is the one OpenWA started, without a window.
const fs = require('fs');
const path = require('path');

const home = process.argv[2];
const mode = process.argv[3];
const out = (o) => { process.stdout.write(JSON.stringify(o)); };

// stdin is a pipe from the engine: read it as a stream (readFileSync(0) fails with EAGAIN on a non-blocking pipe)
async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

async function main() {
  if (mode === 'echo') { const body = await readStdin(); out({ ok: true, length: body.length }); return; } // used by the tests: no browser
  const pp = require(path.join(home, 'node_modules', 'puppeteer-core'));
  const active = fs.readFileSync(path.join(home, 'run', '_IGNORE_chakmati-agent', 'DevToolsActivePort'), 'utf8').trim().split('\n');
  const browser = await pp.connect({ browserWSEndpoint: `ws://127.0.0.1:${active[0]}${active[1]}`, defaultViewport: null });
  try {
    const page = (await browser.pages()).find((p) => p.url().startsWith('https://web.whatsapp.com'));
    if (!page) throw new Error('WhatsApp Web page not found');
    const ready = await page.evaluate(() => !!(window.Store && window.Store.Chat && window.WAPI && window.WAPI.procFiles));
    if (!ready) throw new Error('WhatsApp Web is not ready');
    if (mode === 'check') { out({ ok: true }); return; }
    const input = JSON.parse(await readStdin());
    if (!/^[0-9A-Za-z._-]+@(c\.us|lid|g\.us)$/.test(input.chatId)) throw new Error('invalid chat id');
    const res = await page.evaluate(async (b64, chatId) => {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const file = new File([bytes], 'voice.ogg', { type: 'audio/ogg; codecs=opus' });
      let chat = window.Store.Chat.get(chatId);
      if (!chat && window.Store.WidFactory && window.Store.Chat.find) chat = await window.Store.Chat.find(window.Store.WidFactory.createWid(chatId));
      if (!chat) return { error: 'chat not found' };
      const collection = await window.WAPI.procFiles(chat, file);
      const item = collection.at(0);
      if (!item) return { error: 'could not prepare the audio' };
      await item.mediaPrep.waitForPrep();
      item.mediaPrep.mediaData.type = 'ptt'; // a voice note (the round play button), not an audio file
      const before = chat.msgs.length;
      await item.sendToChat({ chat, options: {} });
      const deadline = Date.now() + 8000;
      while (chat.msgs.length <= before && Date.now() < deadline) await new Promise((r) => setTimeout(r, 100));
      const last = chat.msgs.last();
      if (chat.msgs.length <= before || !last || !last.id || !last.id.fromMe) return { error: 'the message did not appear in the chat' };
      return { id: last.id._serialized, type: last.type };
    }, input.b64, input.chatId);
    if (res.error) throw new Error(res.error);
    out({ ok: true, id: res.id, type: res.type });
  } finally {
    browser.disconnect();
  }
}

main().catch((e) => { out({ ok: false, error: String(e && e.message || e) }); process.exitCode = 1; });
