const express = require('express');
const qrcode = require('qrcode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { Client, LocalAuth } = require('whatsapp-web.js');

const app = express();
app.use(express.json());

const PORT = process.env.BRIDGE_PORT || 3000;
const APP_WEBHOOK_URL = process.env.APP_WEBHOOK_URL || 'http://127.0.0.1:5000/api/whatsapp/inbound';
const FORWARD_GROUPS = String(process.env.FORWARD_GROUPS || 'false').toLowerCase() === 'true';
const INSTANCES_FILE = path.join(__dirname, 'instances.json');

// The original single-session identity is kept as-is so an already-paired
// device doesn't need to re-scan after upgrading to multi-instance support.
const DEFAULT_INSTANCE_ID = 'default';
const DEFAULT_CLIENT_ID = 'detailing-ops';

// instanceId -> { id, clientId, label, client, qr, qrAt, ready, error, phone, createdAt, inboundStats }
const instances = new Map();

function normalizePhoneId(chatId) {
  const raw = String(chatId || '').trim();
  if (!raw) {
    return '';
  }
  const left = raw.split('@')[0] || '';
  return left.replace(/[^0-9]/g, '');
}

function isPlausiblePhone(number) {
  return /^\d{8,15}$/.test(String(number || ''));
}

function extractContactNumber(contact) {
  const candidates = [
    contact?.number,
    contact?.phoneNumber,
  ];
  for (const item of candidates) {
    const normalized = String(item || '').replace(/[^0-9]/g, '');
    if (isPlausiblePhone(normalized)) {
      return normalized;
    }
  }
  return '';
}

async function resolveInboundPhone(client, msg) {
  const from = String(msg.from || '').trim();

  // WhatsApp LID is a privacy identifier, not a reliable phone number.
  // Forward it as identity token so message still appears in inbox,
  // while backend can block auto-reply using chat_id guard.
  if (from.endsWith('@lid')) {
    try {
      const contact = await msg.getContact();
      const number = extractContactNumber(contact);
      if (number) {
        return number;
      }
    } catch (err) {
      // Ignore lookup failures and fallback to lid token.
    }

    const lidUser = from.split('@')[0] || '';
    return `lid:${lidUser}`;
  }

  // Standard 1:1 chat format
  if (from.endsWith('@c.us')) {
    const direct = normalizePhoneId(from);
    if (isPlausiblePhone(direct)) {
      return direct;
    }
  }

  // For privacy identities (e.g. @lid), try resolving actual contact number.
  try {
    const contact = await msg.getContact();
    const number = extractContactNumber(contact);
    if (number) {
      return number;
    }
  } catch (err) {
    // Ignore contact lookup failures and fallback below.
  }

  // Universal fallback: never return empty so message is never dropped.
  const rawUser = from.split('@')[0] || '';
  if (rawUser) {
    return `wa:${rawUser}`;
  }
  return 'wa:unknown';
}

async function forwardInbound(payload) {
  const response = await fetch(APP_WEBHOOK_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`webhook_failed_${response.status}: ${body}`);
  }

  return response.status;
}

function sanitizeId(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
}

function generateInstanceId(label) {
  const base = sanitizeId(label) || 'wa';
  let candidate = `${base}-${crypto.randomBytes(3).toString('hex')}`;
  while (instances.has(candidate)) {
    candidate = `${base}-${crypto.randomBytes(3).toString('hex')}`;
  }
  return candidate;
}

function loadRegisteredInstances() {
  try {
    const raw = fs.readFileSync(INSTANCES_FILE, 'utf8');
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed;
    }
  } catch (err) {
    // No persisted file yet, or it's invalid; start fresh.
  }
  return [];
}

function saveRegisteredInstances() {
  const list = Array.from(instances.values()).map((inst) => ({
    id: inst.id,
    clientId: inst.clientId,
    label: inst.label,
    createdAt: inst.createdAt
  }));
  try {
    fs.writeFileSync(INSTANCES_FILE, JSON.stringify(list, null, 2));
  } catch (err) {
    console.error('Failed to persist instances.json:', err.message || err);
  }
}

function instanceSummary(inst) {
  return {
    id: inst.id,
    client_id: inst.clientId,
    label: inst.label,
    ready: inst.ready,
    connected: inst.ready,
    has_qr: !!inst.qr,
    qr_updated_at: inst.qrAt,
    pairing_code: inst.pairingCode || null,
    pairing_code_at: inst.pairingCodeAt || null,
    phone: inst.phone || '',
    error: inst.error,
    created_at: inst.createdAt,
    inbound_received_count: inst.inboundStats.received,
    inbound_forwarded_count: inst.inboundStats.forwarded,
    inbound_skipped_count: inst.inboundStats.skipped,
    last_inbound_seen_at: inst.inboundStats.lastSeenAt,
    last_inbound_forward_at: inst.inboundStats.lastForwardAt,
    last_inbound_forward_status: inst.inboundStats.lastForwardStatus,
    last_inbound_skipped_reason: inst.inboundStats.lastSkippedReason
  };
}

async function resolvePeerPhone(client, peerId, contact) {
  const id = String(peerId || '').trim();

  if (id.endsWith('@c.us')) {
    const direct = normalizePhoneId(id);
    if (isPlausiblePhone(direct)) {
      return direct;
    }
  }

  const number = extractContactNumber(contact);
  if (number) {
    return number;
  }

  if (id.endsWith('@lid')) {
    return `lid:${id.split('@')[0] || ''}`;
  }

  const user = id.split('@')[0] || '';
  return user ? `wa:${user}` : 'wa:unknown';
}

// Chromium's SingletonLock/SingletonSocket/SingletonCookie embed the host's
// hostname+pid. In Docker, each container recreate gets a new hostname, so a
// lock left behind by the previous (now-dead) container makes Chromium think
// a *different machine* still owns the profile and refuses to launch.
// Safe to clear on our own startup: any prior process is guaranteed gone.
function clearStaleSingletonLock(clientId) {
  const profileDir = path.join(__dirname, '.wwebjs_auth', `session-${clientId}`);
  for (const name of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
    const file = path.join(profileDir, name);
    try {
      fs.unlinkSync(file);
    } catch (err) {
      // Ignore if missing; anything else isn't worth failing startup over.
    }
  }
}

function createInstance({ id, clientId, label }) {
  clearStaleSingletonLock(clientId);

  const inst = {
    id,
    clientId,
    label: label || id,
    client: null,
    qr: null,
    qrAt: null,
    pairingCode: null,
    pairingCodeAt: null,
    ready: false,
    error: null,
    phone: '',
    createdAt: new Date().toISOString(),
    inboundStats: {
      received: 0,
      forwarded: 0,
      skipped: 0,
      lastForwardAt: null,
      lastForwardStatus: null,
      lastSkippedReason: null,
      lastSeenAt: null
    }
  };

  const puppeteerArgs = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',  // containers have 2MB /dev/shm by default — Chrome stalls without this
    '--disable-gpu',
    '--no-first-run',
  ];
  // Opt-in only: for corporate/network TLS-intercepting proxies (e.g. Netskope)
  // where the intercepting CA can't be made to work with Chromium's built-in
  // cert verifier. Never enable this against the open internet.
  if (process.env.WA_BRIDGE_IGNORE_CERT_ERRORS === 'true') {
    puppeteerArgs.push('--ignore-certificate-errors');
  }

  const client = new Client({
    authStrategy: new LocalAuth({ clientId }),
    puppeteer: {
      headless: true,
      args: puppeteerArgs,
      protocolTimeout: 120000,
    }
  });
  inst.client = client;

  client.on('qr', (qr) => {
    inst.qr = qr;
    inst.qrAt = new Date().toISOString();
    inst.ready = false;
    inst.error = null;
    console.log(`[${id}] QR updated at`, inst.qrAt);
  });

  client.on('code', (code) => {
    inst.pairingCode = code;
    inst.pairingCodeAt = new Date().toISOString();
    console.log(`[${id}] Pairing code issued at`, inst.pairingCodeAt);
  });

  client.on('ready', () => {
    inst.ready = true;
    inst.qr = null;
    inst.pairingCode = null;
    inst.phone = (client.info && client.info.wid && client.info.wid.user) || '';
    console.log(`[${id}] WhatsApp client ready (phone=${inst.phone})`);
  });

  client.on('auth_failure', (msg) => {
    inst.ready = false;
    inst.error = `auth_failure: ${msg}`;
    console.error(`[${id}]`, inst.error);
  });

  client.on('disconnected', (reason) => {
    inst.ready = false;
    inst.error = `disconnected: ${reason}`;
    console.error(`[${id}]`, inst.error);
  });

  client.on('message_create', async (msg) => {
    try {
      inst.inboundStats.received += 1;
      inst.inboundStats.lastSeenAt = new Date().toISOString();

      const fromMe = !!msg.fromMe;

      // The OTHER party of the conversation. For our own messages that is the
      // recipient (msg.to), not our own number (msg.from).
      const peerId = String((fromMe ? msg.to : msg.from) || '').trim();
      const isGroup = peerId.endsWith('@g.us');

      // Opsi B: never forward group chats to the CS inbox.
      if (isGroup) {
        inst.inboundStats.skipped += 1;
        inst.inboundStats.lastSkippedReason = 'group_filtered';
        return;
      }

      // Filter the "Message Yourself" / self chat entirely.
      const me = (client.info && client.info.wid && client.info.wid._serialized) || '';
      if (!peerId || (me && peerId === me)) {
        inst.inboundStats.skipped += 1;
        inst.inboundStats.lastSkippedReason = 'self_filtered';
        return;
      }

      const text = String(msg.body || '').trim();

      // Resolve the peer's contact (recipient for our own messages).
      let contactName = '';
      let contactNumber = '';
      let peerContact = null;
      try {
        peerContact = fromMe ? await client.getContactById(peerId) : await msg.getContact();
        contactName = String((peerContact && (peerContact.name || peerContact.pushname)) || '').trim();
        contactNumber = extractContactNumber(peerContact);
      } catch (err) {
        contactName = '';
        contactNumber = '';
      }

      const phone = fromMe
        ? await resolvePeerPhone(client, peerId, peerContact)
        : await resolveInboundPhone(client, msg);

      const payload = {
        phone,
        text,
        source: 'whatsapp-web-bridge',
        message_id: msg.id?._serialized || null,
        timestamp: msg.timestamp || null,
        chat_id: peerId || null,
        is_group: false,
        from_me: fromMe,
        contact_name: contactName,
        contact_number: contactNumber,
        instance_id: id,
        instance_label: inst.label,
        instance_phone: inst.phone || ''
      };

      const statusCode = await forwardInbound(payload);
      inst.inboundStats.forwarded += 1;
      inst.inboundStats.lastForwardAt = new Date().toISOString();
      inst.inboundStats.lastForwardStatus = `ok:${statusCode}`;
      inst.inboundStats.lastSkippedReason = null;
      console.log(`[${id}] Inbound forwarded`, payload.phone, payload.text);
    } catch (err) {
      inst.inboundStats.skipped += 1;
      inst.inboundStats.lastForwardAt = new Date().toISOString();
      inst.inboundStats.lastForwardStatus = `error:${err.message || 'unknown'}`;
      console.error(`[${id}] Inbound forward failed:`, err.message || err);
    }
  });

  instances.set(id, inst);

  client.initialize().catch((err) => {
    inst.error = err.message || 'init_failed';
    console.error(`[${id}] Failed to initialize WhatsApp client:`, inst.error);
  });

  return inst;
}

// Requests a WhatsApp "Link with phone number" pairing code as an alternative
// to scanning the QR (Settings > Linked devices > Link with phone number).
async function requestPairingCodeFor(inst, req, res) {
  if (inst.ready) {
    return res.status(409).json({ ok: false, error: 'already_connected' });
  }

  const phone = String(req.body.phone || '').replace(/[^0-9]/g, '');
  if (!isPlausiblePhone(phone)) {
    return res.status(400).json({ ok: false, error: 'phone must be digits only, including country code (e.g. 6281234567890)' });
  }

  try {
    const code = await inst.client.requestPairingCode(phone);
    inst.pairingCode = code;
    inst.pairingCodeAt = new Date().toISOString();
    return res.json({ ok: true, pairing_code: code });
  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message || 'pairing_code_failed' });
  }
}

async function resolveLidToCUs(client, lidTarget) {
  const lid = String(lidTarget || '').trim().split('@')[0] || '';
  if (!lid) {
    return '';
  }

  try {
    const contact = await client.getContactById(`${lid}@lid`);
    const candidate = extractContactNumber(contact);
    if (candidate) {
      return `${candidate}@c.us`;
    }
  } catch (err) {
    // Ignore and fallback to scanning all contacts.
  }

  try {
    const contacts = await client.getContacts();
    for (const c of contacts) {
      const server = c?.id?.server || '';
      const idUser = String((c?.id && c.id.user) || '').replace(/[^0-9]/g, '');
      if (server === 'lid' && idUser === lid) {
        const candidate = extractContactNumber(c);
        if (candidate) {
          return `${candidate}@c.us`;
        }
      }
    }
  } catch (err) {
    // Ignore if contact scan fails.
  }

  return '';
}

// Sending straight to a raw "<number>@c.us" JID can fail with "No LID for
// user" when WhatsApp Web hasn't cached that contact's LID mapping yet.
// Calling getNumberId() first forces WhatsApp Web to resolve/cache it.
// If getNumberId() resolves to null (no exception), the number is simply not
// registered on WhatsApp — surface that clearly instead of a doomed send.
async function resolveSendTargetId(client, targetId) {
  if (!targetId.endsWith('@c.us')) {
    return { targetId };
  }
  const number = targetId.split('@')[0];
  try {
    const numberId = await client.getNumberId(number);
    if (numberId && numberId._serialized) {
      return { targetId: numberId._serialized };
    }
    return { targetId, notRegistered: true };
  } catch (err) {
    // Lookup itself failed (e.g. transient error); fall back to the raw JID.
    return { targetId };
  }
}

async function sendMessageFor(inst, req, res) {
  const phone = String(req.body.phone || '').trim();
  const chatIdFromBody = String(req.body.chat_id || '').trim();
  const text = String(req.body.text || '').trim();

  if (!text) {
    return res.status(400).json({ ok: false, error: 'text is required' });
  }

  if (!inst.ready) {
    return res.status(409).json({ ok: false, error: 'wa_not_connected' });
  }

  const normalizedPhone = phone.replace(/[^0-9]/g, '');
  let chatId = chatIdFromBody;
  if (!chatId) {
    if (!normalizedPhone) {
      return res.status(400).json({ ok: false, error: 'phone or chat_id is required' });
    }
    chatId = `${normalizedPhone}@c.us`;
  }

  async function attemptSend(targetId) {
    const msg = await inst.client.sendMessage(targetId, text);
    return msg?.id?._serialized ?? msg?._serialized ?? null;
  }

  async function sendWithFallback(targetId) {
    const resolved = await resolveSendTargetId(inst.client, targetId);
    if (resolved.notRegistered) {
      throw new Error(`number_not_on_whatsapp: ${targetId}`);
    }
    const resolvedId = resolved.targetId;
    try {
      return await attemptSend(resolvedId);
    } catch (err) {
      const errMsg = String(err?.message || err || 'send_failed');
      if (resolvedId.endsWith('@lid') || targetId.endsWith('@lid')) {
        const fallbackId = await resolveLidToCUs(inst.client, resolvedId.endsWith('@lid') ? resolvedId : targetId);
        if (fallbackId) {
          try {
            const fallbackMsgId = await attemptSend(fallbackId);
            return fallbackMsgId;
          } catch (fallbackErr) {
            throw new Error(`${errMsg}; fallback=${String(fallbackErr?.message || fallbackErr || 'send_failed')}`);
          }
        }
      }
      throw err;
    }
  }

  try {
    const messageId = await sendWithFallback(chatId);
    return res.json({ ok: true, status: 'sent', id: messageId });
  } catch (err) {
    const errMsg = String(err?.message || err || 'send_failed');
    return res.status(500).json({ ok: false, error: errMsg });
  }
}

// Strict validation for save-time checks: confirms a number is a real,
// active WhatsApp account (not just a plausible-looking digit string).
async function checkNumberFor(inst, req, res) {
  const phone = String(req.body.phone || '').replace(/[^0-9]/g, '');
  if (!isPlausiblePhone(phone)) {
    return res.status(400).json({ ok: false, error: 'invalid_phone' });
  }
  if (!inst.ready) {
    return res.status(409).json({ ok: false, error: 'wa_not_connected' });
  }
  try {
    const numberId = await inst.client.getNumberId(phone);
    const registered = !!(numberId && numberId._serialized);
    return res.json({ ok: true, registered, serialized: registered ? numberId._serialized : null });
  } catch (err) {
    return res.status(500).json({ ok: false, error: String(err?.message || err || 'check_failed') });
  }
}

// ---- Multi-instance management (register additional WhatsApp numbers via QR) ----

app.get('/instances', (req, res) => {
  const list = Array.from(instances.values()).map(instanceSummary);
  res.json({ ok: true, count: list.length, instances: list });
});

app.post('/instances', (req, res) => {
  const label = String(req.body.label || '').trim();
  if (!label) {
    return res.status(400).json({ ok: false, error: 'label is required' });
  }
  const id = generateInstanceId(label);
  const inst = createInstance({ id, clientId: id, label });
  saveRegisteredInstances();
  res.status(201).json({ ok: true, instance: instanceSummary(inst) });
});

app.get('/instances/:id/status', (req, res) => {
  const inst = instances.get(req.params.id);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'instance_not_found' });
  }
  res.json({ ok: true, instance: instanceSummary(inst) });
});

app.get('/instances/:id/qr', async (req, res) => {
  const inst = instances.get(req.params.id);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'instance_not_found' });
  }
  if (!inst.qr) {
    return res.status(404).json({ ok: false, error: 'qr_not_ready' });
  }

  try {
    const png = await qrcode.toBuffer(inst.qr, { type: 'png', width: 320, margin: 1 });
    res.setHeader('Content-Type', 'image/png');
    res.send(png);
  } catch (err) {
    res.status(500).json({ ok: false, error: 'qr_render_failed' });
  }
});

app.post('/instances/:id/send-message', async (req, res) => {
  const inst = instances.get(req.params.id);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'instance_not_found' });
  }
  await sendMessageFor(inst, req, res);
});

app.post('/instances/:id/check-number', async (req, res) => {
  const inst = instances.get(req.params.id);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'instance_not_found' });
  }
  await checkNumberFor(inst, req, res);
});

app.post('/instances/:id/pair', async (req, res) => {
  const inst = instances.get(req.params.id);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'instance_not_found' });
  }
  await requestPairingCodeFor(inst, req, res);
});

app.delete('/instances/:id', async (req, res) => {
  const id = req.params.id;
  const inst = instances.get(id);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'instance_not_found' });
  }
  if (id === DEFAULT_INSTANCE_ID) {
    return res.status(400).json({ ok: false, error: 'cannot_delete_default_instance' });
  }

  try {
    await inst.client.logout();
  } catch (err) {
    // Ignore logout failures (e.g. already disconnected) and continue cleanup.
  }
  try {
    await inst.client.destroy();
  } catch (err) {
    // Ignore destroy failures and continue cleanup.
  }

  instances.delete(id);
  saveRegisteredInstances();
  res.json({ ok: true });
});

// ---- Legacy single-session endpoints (kept for backward compatibility; they
// always operate on the "default" instance). ----

app.get('/health', (req, res) => {
  const inst = instances.get(DEFAULT_INSTANCE_ID);
  res.json({
    ok: true,
    service: 'wa-real-bridge',
    status: inst && inst.ready ? 'ready' : 'waiting_qr',
    connected: !!(inst && inst.ready)
  });
});

app.get('/status', (req, res) => {
  const inst = instances.get(DEFAULT_INSTANCE_ID);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'default_instance_missing' });
  }
  const summary = instanceSummary(inst);
  res.json({
    ok: true,
    connected: summary.connected,
    auth_required: !summary.connected,
    has_qr: summary.has_qr,
    qr_updated_at: summary.qr_updated_at,
    pairing_code: summary.pairing_code,
    pairing_code_at: summary.pairing_code_at,
    error: summary.error,
    webhook_url: APP_WEBHOOK_URL,
    forward_groups: FORWARD_GROUPS,
    inbound_received_count: summary.inbound_received_count,
    inbound_forwarded_count: summary.inbound_forwarded_count,
    inbound_skipped_count: summary.inbound_skipped_count,
    last_inbound_seen_at: summary.last_inbound_seen_at,
    last_inbound_forward_at: summary.last_inbound_forward_at,
    last_inbound_forward_status: summary.last_inbound_forward_status,
    last_inbound_skipped_reason: summary.last_inbound_skipped_reason
  });
});

app.post('/pair', async (req, res) => {
  const inst = instances.get(DEFAULT_INSTANCE_ID);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'default_instance_missing' });
  }
  await requestPairingCodeFor(inst, req, res);
});

app.get('/qr', async (req, res) => {
  const inst = instances.get(DEFAULT_INSTANCE_ID);
  if (!inst || !inst.qr) {
    return res.status(404).json({ ok: false, error: 'qr_not_ready' });
  }

  try {
    const png = await qrcode.toBuffer(inst.qr, { type: 'png', width: 320, margin: 1 });
    res.setHeader('Content-Type', 'image/png');
    res.send(png);
  } catch (err) {
    res.status(500).json({ ok: false, error: 'qr_render_failed' });
  }
});

app.get('/contacts', async (req, res) => {
  const inst = instances.get(DEFAULT_INSTANCE_ID);
  if (!inst || !inst.ready) {
    return res.status(409).json({ ok: false, error: 'wa_not_connected' });
  }

  const savedOnly = String(req.query.saved_only || 'true').toLowerCase() !== 'false';

  try {
    const contacts = await inst.client.getContacts();
    const byKey = new Map();
    for (const c of contacts) {
      if (c.isGroup || c.isMe) {
        continue;
      }
      if (savedOnly && !c.isMyContact) {
        continue;
      }

      const server = c.id && c.id.server ? String(c.id.server) : '';
      const idUser = String((c.id && c.id.user) || '').replace(/[^0-9]/g, '');
      const dotNumber = String(c.number || '').replace(/[^0-9]/g, '');

      // Resolve the real phone number and the private LID separately.
      // WhatsApp returns both a @c.us identity (real number in id.user) and a
      // @lid identity for the same person; the two are linked by a shared
      // id.user, while the differing `.number` value carries the LID.
      let phone = '';
      let lid = '';

      if (server === 'c.us' && isPlausiblePhone(idUser)) {
        phone = idUser;
        if (dotNumber && dotNumber !== idUser && isPlausiblePhone(dotNumber)) {
          lid = dotNumber;
        }
      } else if (server === 'lid') {
        if (isPlausiblePhone(idUser)) {
          lid = idUser;
        }
        if (dotNumber && dotNumber !== idUser && isPlausiblePhone(dotNumber)) {
          phone = dotNumber;
        }
      } else {
        const fallback = isPlausiblePhone(idUser) ? idUser : dotNumber;
        if (isPlausiblePhone(fallback)) {
          phone = fallback;
        }
      }

      // A record is only useful if it carries at least a real number or a LID.
      const key = phone || lid;
      if (!key) {
        continue;
      }

      const name = String(c.name || c.pushname || '').trim();
      const existing = byKey.get(key) || {
        number: '',
        lid: '',
        name: '',
        is_my_contact: false,
        is_business: false
      };

      if (phone) {
        existing.number = phone;
      }
      if (lid && !existing.lid) {
        existing.lid = lid;
      }
      if (!existing.name && name) {
        existing.name = name;
      }
      existing.is_my_contact = existing.is_my_contact || !!c.isMyContact;
      existing.is_business = existing.is_business || !!c.isBusiness;
      byKey.set(key, existing);
    }

    const result = Array.from(byKey.values());
    res.json({ ok: true, count: result.length, contacts: result });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message || 'contacts_failed' });
  }
});

app.post('/send-message', async (req, res) => {
  const inst = instances.get(DEFAULT_INSTANCE_ID);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'default_instance_missing' });
  }
  await sendMessageFor(inst, req, res);
});

app.post('/check-number', async (req, res) => {
  const inst = instances.get(DEFAULT_INSTANCE_ID);
  if (!inst) {
    return res.status(404).json({ ok: false, error: 'default_instance_missing' });
  }
  await checkNumberFor(inst, req, res);
});

app.listen(PORT, async () => {
  console.log(`Bridge listening on http://127.0.0.1:${PORT}`);

  const registered = loadRegisteredInstances();
  if (!registered.some((entry) => entry.id === DEFAULT_INSTANCE_ID)) {
    registered.unshift({
      id: DEFAULT_INSTANCE_ID,
      clientId: DEFAULT_CLIENT_ID,
      label: 'Default',
      createdAt: new Date().toISOString()
    });
  }

  for (const entry of registered) {
    createInstance({
      id: entry.id,
      clientId: entry.clientId || entry.id,
      label: entry.label || entry.id
    });
  }
  saveRegisteredInstances();
});

