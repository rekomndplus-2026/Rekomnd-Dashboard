/**
 * wa-server/server.js
 * =====================================================
 * Lightweight WhatsApp gateway — replaces Evolution API + Docker.
 * Uses @whiskeysockets/baileys to connect directly to WhatsApp Web.
 *
 * Exposes a REST API fully compatible with what the FastAPI backend expects:
 *   POST /instance/create
 *   GET  /instance/connect/:instance
 *   GET  /instance/connectionState/:instance
 *   GET  /instance/fetchInstances
 *   DELETE /instance/logout/:instance
 *   DELETE /instance/delete/:instance
 *   POST /message/sendText/:instance
 *   POST /message/sendMedia/:instance
 *   GET  /chat/whatsappNumbers/:instance
 *   GET  /group/fetchAllGroups/:instance
 *   GET  /group/participants/:instance
 *
 * No Docker, No Redis, No PostgreSQL needed.
 * Session data is stored locally in ./sessions/
 */

const express = require('express');
const qrcode  = require('qrcode');
const path    = require('path');
const fs      = require('fs');
const pino    = require('pino');
const http    = require('http');

// ── Baileys import ──────────────────────────────────────────────────────────
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  isJidGroup,
} = require('@whiskeysockets/baileys');

// ── Config ──────────────────────────────────────────────────────────────────
const PORT        = parseInt(process.env.PORT || '8085', 10);
const API_KEY     = process.env.API_KEY || 'supersecretapikey';
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:3001';
const SESSIONS_DIR = path.join(__dirname, 'sessions');
const MONITOR_GROUPS_FILE = path.join(__dirname, 'monitor_groups.json');
const logger = pino({ level: 'info' }, pino.destination(1));

fs.mkdirSync(SESSIONS_DIR, { recursive: true });

// ── In-memory instance registry ─────────────────────────────────────────────
// Each entry: { sock, state, qrBase64, phone, profileName, status }
// status: 'connecting' | 'qr' | 'open' | 'close'
const instances = {};

// ── Express app ─────────────────────────────────────────────────────────────
const app = express();
app.use(express.json({ limit: '50mb' }));

// CORS for REKOMND+ shell
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, apikey');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

// Simple API-key middleware
app.use((req, res, next) => {
  const key = req.headers['apikey'] || req.query.apikey;
  if (key !== API_KEY) {
    return res.status(401).json({ error: 'Unauthorized — wrong apikey header' });
  }
  next();
});

// ── Helpers ──────────────────────────────────────────────────────────────────
function getOrNull(name) { return instances[name] || null; }

function loadMonitoredGroups() {
  try {
    if (fs.existsSync(MONITOR_GROUPS_FILE)) {
      return JSON.parse(fs.readFileSync(MONITOR_GROUPS_FILE, 'utf-8'));
    }
  } catch (_) {}
  return [];
}

function saveMonitoredGroups(groups) {
  fs.writeFileSync(MONITOR_GROUPS_FILE, JSON.stringify(groups, null, 2));
}

function forwardGroupMessage(instanceName, msgData) {
  const monitored = loadMonitoredGroups();
  if (!monitored.length) return;

  const key = msgData.key || {};
  const remoteJid = key.remoteJid || '';
  if (!remoteJid.endsWith('@g.us')) return;
  if (key.fromMe) return;
  if (!monitored.includes(remoteJid)) return;

  // Extract text
  const message = msgData.message || {};
  let text = '';
  if (message.conversation) text = message.conversation;
  else if (message.extendedTextMessage) text = message.extendedTextMessage.text || '';
  else if (message.imageMessage) text = message.imageMessage.caption || '';
  else if (message.videoMessage) text = message.videoMessage.caption || '';
  if (!text.trim()) return;

  // Build Evolution-API-compatible webhook payload
  const payload = {
    event: 'messages.upsert',
    instance: instanceName,
    data: {
      key: {
        remoteJid: remoteJid,
        fromMe: false,
        id: key.id || '',
        participant: key.participant || '',
      },
      pushName: msgData.pushName || '',
      message: { conversation: text },
    },
  };

  const body = JSON.stringify(payload);
  const url = new URL(`${BACKEND_URL}/api/monitor/webhook`);
  const options = {
    hostname: url.hostname,
    port: url.port,
    path: url.pathname,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
  };

  const req = http.request(options, (res) => {
    let data = '';
    res.on('data', (chunk) => { data += chunk; });
    res.on('end', () => {
      try {
        const parsed = JSON.parse(data);
        if (parsed.leads_saved > 0) {
          logger.info({ instance: instanceName, group: remoteJid, leads: parsed.leads_saved }, '[Monitor] Lead(s) saved');
        }
      } catch (_) {}
    });
  });
  req.on('error', (err) => {
    logger.error({ err }, '[Monitor] Failed to forward message to backend');
  });
  req.write(body);
  req.end();
}

async function startInstance(name) {
  const sessionPath = path.join(SESSIONS_DIR, name);
  fs.mkdirSync(sessionPath, { recursive: true });

  const { state, saveCreds } = await useMultiFileAuthState(sessionPath);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    logger: logger.child({ instance: name }),
    printQRInTerminal: false,
    browser: ['REKOMND+', 'Chrome', '126.0'],
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
  });

  instances[name] = {
    sock,
    status: 'connecting',
    qrBase64: null,
    phone: '',
    profileName: '',
  };

  // Persist credentials on update
  sock.ev.on('creds.update', saveCreds);

  // Forward group messages for lead monitoring
  sock.ev.on('messages.upsert', (upsert) => {
    if (upsert.type !== 'notify') return;
    for (const msg of upsert.messages) {
      forwardGroupMessage(name, msg);
    }
  });

  // Handle QR codes
  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      try {
        const base64 = await qrcode.toDataURL(qr, { width: 300 });
        instances[name].qrBase64 = base64;
        instances[name].status   = 'qr';
        logger.info({ instance: name }, 'QR code ready');
      } catch (err) {
        logger.error({ err }, 'QR generation failed');
      }
    }

    if (connection === 'open') {
      instances[name].status   = 'open';
      instances[name].qrBase64 = null;
      const me = sock.user;
      instances[name].phone       = me?.id?.split(':')[0]?.split('@')[0] || '';
      instances[name].profileName = me?.name || '';
      logger.info({ instance: name, phone: instances[name].phone }, 'WhatsApp connected ✓');
    }

    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = code !== DisconnectReason.loggedOut;
      logger.info({ instance: name, code, shouldReconnect }, 'Connection closed');

      if (shouldReconnect) {
        instances[name].status = 'connecting';
        // Reconnect after a short delay
        setTimeout(() => startInstance(name), 3000);
      } else {
        instances[name].status   = 'close';
        instances[name].qrBase64 = null;
        // Clear session so next connect generates fresh QR
        fs.rmSync(path.join(SESSIONS_DIR, name), { recursive: true, force: true });
      }
    }
  });

  return instances[name];
}

// ── Routes ───────────────────────────────────────────────────────────────────

// ── Monitored Groups Management ──────────────────────────────────────────────
app.get('/monitor/groups', (_req, res) => {
  res.json({ groups: loadMonitoredGroups() });
});

app.post('/monitor/groups', (req, res) => {
  const { group_ids } = req.body;
  if (!Array.isArray(group_ids)) return res.status(400).json({ error: 'group_ids array required' });
  const current = loadMonitoredGroups();
  const merged = [...new Set([...current, ...group_ids])];
  saveMonitoredGroups(merged);
  res.json({ groups: merged, message: `${group_ids.length} group(s) added to monitor` });
});

app.delete('/monitor/groups', (req, res) => {
  const { group_ids } = req.body;
  if (!Array.isArray(group_ids)) return res.status(400).json({ error: 'group_ids array required' });
  const current = loadMonitoredGroups();
  const filtered = current.filter(g => !group_ids.includes(g));
  saveMonitoredGroups(filtered);
  res.json({ groups: filtered, message: `${group_ids.length} group(s) removed from monitor` });
});

// Health check (no auth needed)
app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'wa-baileys-server', version: '1.0.0' });
});

/**
 * POST /instance/create
 * Body: { instanceName, qrcode: true, integration: "WHATSAPP-BAILEYS" }
 */
app.post('/instance/create', async (req, res) => {
  const name = req.body?.instanceName;
  if (!name) return res.status(400).json({ error: 'instanceName required' });

  if (instances[name] && instances[name].status === 'open') {
    return res.status(409).json({ error: 'Instance already connected', instanceName: name });
  }

  // Start or restart instance
  await startInstance(name);
  const inst = instances[name];

  // Wait up to 20 s for QR code to appear
  let waited = 0;
  while (!inst.qrBase64 && inst.status !== 'open' && waited < 20000) {
    await new Promise(r => setTimeout(r, 500));
    waited += 500;
  }

  res.json({
    instance: { instanceName: name, status: inst.status },
    qrcode: inst.qrBase64 ? { base64: inst.qrBase64 } : null,
  });
});

/**
 * GET /instance/connect/:instance
 * Returns current QR code base64 (used by backend for QR refresh)
 */
app.get('/instance/connect/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);

  if (!inst) {
    // Auto-start if not running
    await startInstance(name);
    let waited = 0;
    while (!instances[name].qrBase64 && instances[name].status !== 'open' && waited < 20000) {
      await new Promise(r => setTimeout(r, 500));
      waited += 500;
    }
  }

  const current = instances[name];
  if (current?.status === 'open') {
    return res.json({ connected: true, base64: null });
  }

  if (current?.qrBase64) {
    return res.json({ base64: current.qrBase64 });
  }

  res.json({ base64: null, status: current?.status || 'connecting' });
});

/**
 * GET /instance/connectionState/:instance
 */
app.get('/instance/connectionState/:instance', (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  const state = inst?.status === 'open' ? 'open'
              : inst?.status === 'connecting' || inst?.status === 'qr' ? 'connecting'
              : 'close';
  res.json({ instance: { instanceName: name, state } });
});

/**
 * GET /instance/fetchInstances[?instanceName=xxx]
 */
app.get('/instance/fetchInstances', (req, res) => {
  const filter = req.query.instanceName;
  const list = Object.entries(instances).map(([name, inst]) => ({
    instance: {
      instanceName: name,
      state: inst.status === 'open' ? 'open' : 'close',
      ownerJid: inst.phone ? `${inst.phone}@s.whatsapp.net` : '',
      profileName: inst.profileName,
    },
  }));
  if (filter) {
    return res.json(list.filter(i => i.instance.instanceName === filter));
  }
  res.json(list);
});

/**
 * DELETE /instance/logout/:instance
 */
app.delete('/instance/logout/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  if (!inst) return res.json({ message: 'Instance not found' });
  try {
    await inst.sock.logout();
  } catch (_) {}
  instances[name].status   = 'close';
  instances[name].qrBase64 = null;
  res.json({ message: 'Logged out' });
});

/**
 * DELETE /instance/delete/:instance
 */
app.delete('/instance/delete/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  if (inst) {
    try { await inst.sock.end(undefined); } catch (_) {}
    delete instances[name];
  }
  fs.rmSync(path.join(SESSIONS_DIR, name), { recursive: true, force: true });
  res.json({ message: 'Deleted' });
});

/**
 * POST /message/sendText/:instance
 * Body: { number, text, delay? }
 */
app.post('/message/sendText/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  if (!inst || inst.status !== 'open') {
    return res.status(400).json({ error: 'Instance not connected' });
  }

  const { number, text, delay = 1000 } = req.body;
  if (!number || !text) return res.status(400).json({ error: 'number and text required' });

  // Apply optional delay
  if (delay > 0) await new Promise(r => setTimeout(r, delay));

  try {
    const jid = number.includes('@') ? number : `${number.replace(/\D/g, '')}@s.whatsapp.net`;
    const result = await inst.sock.sendMessage(jid, { text });
    res.json({ key: result?.key, status: 'sent', number });
  } catch (err) {
    logger.error({ err }, 'sendText failed');
    res.status(500).json({ error: err.message });
  }
});

/**
 * POST /message/sendMedia/:instance
 * Body: { number, caption, media (base64), mediatype, fileName, options? }
 */
app.post('/message/sendMedia/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  if (!inst || inst.status !== 'open') {
    return res.status(400).json({ error: 'Instance not connected' });
  }

  const { number, caption, media, mediatype, fileName, options = {} } = req.body;
  if (!number || !media) return res.status(400).json({ error: 'number and media required' });

  const delay = options?.delay || 1200;
  if (delay > 0) await new Promise(r => setTimeout(r, delay));

  try {
    const jid = number.includes('@') ? number : `${number.replace(/\D/g, '')}@s.whatsapp.net`;
    const buffer = Buffer.from(media, 'base64');

    let msgContent;
    if (mediatype === 'image') {
      msgContent = { image: buffer, caption };
    } else if (mediatype === 'video') {
      msgContent = { video: buffer, caption };
    } else if (mediatype === 'audio') {
      msgContent = { audio: buffer, ptt: false };
    } else {
      msgContent = { document: buffer, fileName: fileName || 'file', caption };
    }

    const result = await inst.sock.sendMessage(jid, msgContent);
    res.json({ key: result?.key, status: 'sent', number });
  } catch (err) {
    logger.error({ err }, 'sendMedia failed');
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /chat/whatsappNumbers/:instance?numbers=123456
 * Check if a number is registered on WhatsApp
 */
app.get('/chat/whatsappNumbers/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  if (!inst || inst.status !== 'open') return res.json([{ exists: false }]);

  const raw = req.query.numbers || '';
  const nums = (Array.isArray(raw) ? raw : [raw]).map(n => n.replace(/\D/g, ''));

  try {
    const results = await Promise.all(
      nums.map(async n => {
        try {
          const [result] = await inst.sock.onWhatsApp(`${n}@s.whatsapp.net`);
          return { number: n, exists: !!result?.exists };
        } catch {
          return { number: n, exists: true }; // Default to true if check fails
        }
      })
    );
    res.json(results);
  } catch (err) {
    res.json(nums.map(n => ({ number: n, exists: true })));
  }
});

/**
 * GET /group/fetchAllGroups/:instance
 */
app.get('/group/fetchAllGroups/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  if (!inst || inst.status !== 'open') {
    return res.json([]);
  }

  try {
    const groupMap = await inst.sock.groupFetchAllParticipating();
    const groups = Object.values(groupMap).map(g => ({
      id: g.id,
      subject: g.subject,
      size: g.size,
      participants: (g.participants || []).map(p => ({
        id: p.id,
        admin: p.admin || null,
      })),
    }));
    res.json(groups);
  } catch (err) {
    logger.error({ err }, 'fetchAllGroups failed');
    res.json([]);
  }
});

/**
 * GET /group/participants/:instance?groupJid=xxx
 * Returns participants with resolved phone numbers where possible.
 */
app.get('/group/participants/:instance', async (req, res) => {
  const name = req.params.instance;
  const inst = getOrNull(name);
  if (!inst || inst.status !== 'open') return res.json([]);

  const groupJid = req.query.groupJid;
  if (!groupJid) return res.status(400).json({ error: 'groupJid required' });

  try {
    const meta = await inst.sock.groupMetadata(groupJid);
    const participants = meta.participants || [];

    // Resolve phone numbers from JIDs and contacts store
    const result = participants.map(p => {
      const jid = p.id || '';
      let phone = '';
      let idType = 'phone';

      if (jid.endsWith('@lid')) {
        idType = 'lid';
        // LID — no phone number available from JID alone
        phone = '';
      } else {
        // Phone-based JID: "1234567890:12@s.whatsapp.net" → "1234567890"
        phone = jid.split(':')[0].split('@')[0];
      }

      return {
        id: jid,
        phone: phone,
        admin: p.admin || null,
        idType: idType,
      };
    });

    res.json(result);
  } catch (err) {
    logger.error({ err }, 'group participants failed');
    res.json([]);
  }
});

/**
 * POST /webhook/set/:instance  (stub — not used without redis)
 */
app.post('/webhook/set/:instance', (_req, res) => {
  res.json({ message: 'Webhook not used in no-docker mode' });
});

// ── Start ────────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`\n✅ wa-baileys-server running on http://localhost:${PORT}`);
  console.log(`   API Key  : ${API_KEY}`);
  console.log(`   Sessions : ${SESSIONS_DIR}`);
  console.log(`   No Docker · No Redis · No PostgreSQL\n`);
});
