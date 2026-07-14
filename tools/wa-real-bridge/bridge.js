const express = require('express');
const qrcode = require('qrcode');
const { Client, LocalAuth } = require('whatsapp-web.js');

const app = express();
app.use(express.json());

const PORT = process.env.BRIDGE_PORT || 3000;
const APP_WEBHOOK_URL = process.env.APP_WEBHOOK_URL || 'http://127.0.0.1:5000/api/whatsapp/inbound';
const FORWARD_GROUPS = String(process.env.FORWARD_GROUPS || 'false').toLowerCase() === 'true';

let latestQr = null;
let latestQrAt = null;
let ready = false;
let lastError = null;
let lastInboundForwardAt = null;
let lastInboundForwardStatus = null;
let lastInboundSkippedReason = null;
let inboundReceivedCount = 0;
let inboundForwardedCount = 0;
let inboundSkippedCount = 0;
let lastInboundSeenAt = null;

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

async function resolveInboundPhone(msg) {
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

const client = new Client({
  authStrategy: new LocalAuth({ clientId: 'detailing-ops' }),
  puppeteer: {
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  }
});

client.on('qr', (qr) => {
  latestQr = qr;
  latestQrAt = new Date().toISOString();
  ready = false;
  lastError = null;
  console.log('QR updated at', latestQrAt);
});

client.on('ready', () => {
  ready = true;
  latestQr = null;
  console.log('WhatsApp client ready');
});

client.on('auth_failure', (msg) => {
  ready = false;
  lastError = `auth_failure: ${msg}`;
  console.error(lastError);
});

client.on('disconnected', (reason) => {
  ready = false;
  lastError = `disconnected: ${reason}`;
  console.error(lastError);
});

async function resolvePeerPhone(peerId, contact) {
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

client.on('message_create', async (msg) => {
  try {
    inboundReceivedCount += 1;
    lastInboundSeenAt = new Date().toISOString();

    const fromMe = !!msg.fromMe;

    // The OTHER party of the conversation. For our own messages that is the
    // recipient (msg.to), not our own number (msg.from).
    const peerId = String((fromMe ? msg.to : msg.from) || '').trim();
    const isGroup = peerId.endsWith('@g.us');

    // Opsi B: never forward group chats to the CS inbox.
    if (isGroup) {
      inboundSkippedCount += 1;
      lastInboundSkippedReason = 'group_filtered';
      return;
    }

    // Filter the "Message Yourself" / self chat entirely.
    const me = (client.info && client.info.wid && client.info.wid._serialized) || '';
    if (!peerId || (me && peerId === me)) {
      inboundSkippedCount += 1;
      lastInboundSkippedReason = 'self_filtered';
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
      ? await resolvePeerPhone(peerId, peerContact)
      : await resolveInboundPhone(msg);

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
      contact_number: contactNumber
    };

    const statusCode = await forwardInbound(payload);
    inboundForwardedCount += 1;
    lastInboundForwardAt = new Date().toISOString();
    lastInboundForwardStatus = `ok:${statusCode}`;
    lastInboundSkippedReason = null;
    console.log('Inbound forwarded', payload.phone, payload.text);
  } catch (err) {
    inboundSkippedCount += 1;
    lastInboundForwardAt = new Date().toISOString();
    lastInboundForwardStatus = `error:${err.message || 'unknown'}`;
    console.error('Inbound forward failed:', err.message || err);
  }
});

app.get('/health', (req, res) => {
  res.json({
    ok: true,
    service: 'wa-real-bridge',
    status: ready ? 'ready' : 'waiting_qr',
    connected: ready
  });
});

app.get('/status', (req, res) => {
  res.json({
    ok: true,
    connected: ready,
    auth_required: !ready,
    has_qr: !!latestQr,
    qr_updated_at: latestQrAt,
    error: lastError,
    webhook_url: APP_WEBHOOK_URL,
    forward_groups: FORWARD_GROUPS,
    inbound_received_count: inboundReceivedCount,
    inbound_forwarded_count: inboundForwardedCount,
    inbound_skipped_count: inboundSkippedCount,
    last_inbound_seen_at: lastInboundSeenAt,
    last_inbound_forward_at: lastInboundForwardAt,
    last_inbound_forward_status: lastInboundForwardStatus,
    last_inbound_skipped_reason: lastInboundSkippedReason
  });
});

app.get('/qr', async (req, res) => {
  if (!latestQr) {
    return res.status(404).json({ ok: false, error: 'qr_not_ready' });
  }

  try {
    const png = await qrcode.toBuffer(latestQr, { type: 'png', width: 320, margin: 1 });
    res.setHeader('Content-Type', 'image/png');
    res.send(png);
  } catch (err) {
    res.status(500).json({ ok: false, error: 'qr_render_failed' });
  }
});

app.get('/contacts', async (req, res) => {
  if (!ready) {
    return res.status(409).json({ ok: false, error: 'wa_not_connected' });
  }

  const savedOnly = String(req.query.saved_only || 'true').toLowerCase() !== 'false';

  try {
    const contacts = await client.getContacts();
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
  const phone = String(req.body.phone || '').trim();
  const chatIdFromBody = String(req.body.chat_id || '').trim();
  const text = String(req.body.text || '').trim();

  if (!text) {
    return res.status(400).json({ ok: false, error: 'text is required' });
  }

  if (!ready) {
    return res.status(409).json({ ok: false, error: 'wa_not_connected' });
  }

  let chatId = chatIdFromBody;
  if (!chatId) {
    if (!phone) {
      return res.status(400).json({ ok: false, error: 'phone or chat_id is required' });
    }
    const normalized = phone.replace(/[^0-9]/g, '');
    chatId = `${normalized}@c.us`;
  }

  try {
    const msg = await client.sendMessage(chatId, text);
    return res.json({ ok: true, status: 'sent', id: msg.id?._serialized || null });
  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message || 'send_failed' });
  }
});

app.listen(PORT, async () => {
  console.log(`Bridge listening on http://127.0.0.1:${PORT}`);
  try {
    await client.initialize();
  } catch (err) {
    lastError = err.message || 'init_failed';
    console.error('Failed to initialize WhatsApp client:', lastError);
  }
});
