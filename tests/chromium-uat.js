#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');

const baseUrl = process.env.BASE_URL || 'http://localhost:8080';
const loginUser = process.env.UAT_USER || 'admin';
const loginPassword = process.env.UAT_PASSWORD || '';
const chromiumCandidates = [
  process.env.CHROMIUM_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/chromium',
  '/usr/bin/google-chrome',
  '/opt/homebrew/bin/chromium',
].filter(Boolean);

function fail(message) {
  console.error(`UAT failed: ${message}`);
  process.exit(1);
}

function findChromium() {
  for (const candidate of chromiumCandidates) {
    if (!candidate) continue;
    try {
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    } catch {
      // ignore
    }
  }
  const which = spawnSync('which', ['chromium'], { encoding: 'utf8' });
  if (which.status === 0) {
    return which.stdout.trim();
  }
  fail('Could not find a Chromium executable. Set CHROMIUM_PATH to the browser binary.');
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(fn, timeoutMs = 10000, intervalMs = 250) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await sleep(intervalMs);
  }
  throw lastError || new Error('Timed out waiting for condition');
}

async function main() {
  if (!loginPassword) {
    fail('UAT_PASSWORD is required. Set env var UAT_PASSWORD before running UAT.');
  }

  const chromium = findChromium();
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bmw-chromium-uat-'));
  const remoteDebuggingPort = 9222;
  const chrome = spawn(
    chromium,
    [
      `--remote-debugging-port=${remoteDebuggingPort}`,
      '--headless=new',
      '--disable-gpu',
      '--no-sandbox',
      '--disable-dev-shm-usage',
      `--user-data-dir=${userDataDir}`,
      baseUrl,
    ],
    { stdio: 'ignore' },
  );

  process.on('exit', () => {
    try {
      chrome.kill('SIGKILL');
    } catch {
      // ignore
    }
    try {
      fs.rmSync(userDataDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  const fetchJson = async (url) => {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for ${url}`);
    }
    return response.json();
  };

  await waitFor(() => fetchJson(`http://127.0.0.1:${remoteDebuggingPort}/json/version`));
  const pageTarget = await waitFor(async () => {
    const targets = await fetchJson(`http://127.0.0.1:${remoteDebuggingPort}/json/list`);
    return targets.find((target) => target.type === 'page') || null;
  });

  const wsUrl = pageTarget.webSocketDebuggerUrl;
  if (!wsUrl) {
    fail('Chromium did not expose a page target.');
  }

  const socket = new WebSocket(wsUrl);
  const pending = new Map();
  let nextId = 1;

  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });

  const waitForEvent = (eventName, predicate = () => true, timeoutMs = 10000) => new Promise((resolve, reject) => {
    const started = Date.now();
    const interval = setInterval(() => {
      if (Date.now() - started > timeoutMs) {
        clearInterval(interval);
        reject(new Error(`Timed out waiting for ${eventName}`));
      }
    }, 200);
    const previousHandler = socket.onmessage;
    socket.onmessage = (event) => {
      if (typeof previousHandler === 'function') {
        previousHandler.call(socket, event);
      }
      const payload = JSON.parse(event.data.toString());
      if (payload.method === eventName && predicate(payload.params || {})) {
        clearInterval(interval);
        socket.onmessage = previousHandler;
        resolve(payload.params);
      }
    };
  });

  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });

  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data.toString());
    if (payload.id && pending.has(payload.id)) {
      const handlers = pending.get(payload.id);
      pending.delete(payload.id);
      if (payload.error) {
        handlers.reject(new Error(payload.error.message || 'Protocol error'));
      } else {
        handlers.resolve(payload.result);
      }
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');

  const navigate = async (url) => {
    const navigation = waitForEvent('Page.loadEventFired');
    await send('Page.navigate', { url });
    await navigation;
  };

  const evalText = async (expression) => {
    const result = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    return result.result.value;
  };

  const click = async (selector) => {
    const expression = `(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      el.scrollIntoView({ block: 'center', inline: 'center' });
      el.click();
      return true;
    })()`;
    return evalText(expression);
  };

  const typeInto = async (selector, value) => {
    const expression = `(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      el.focus();
      el.value = ${JSON.stringify(value)};
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`;
    return evalText(expression);
  };

  const select = async (selector, value) => {
    const expression = `(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      el.value = ${JSON.stringify(value)};
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`;
    return evalText(expression);
  };

  const textContains = async (needle) => {
    const expression = `(() => document.body && document.body.innerText.includes(${JSON.stringify(needle)}))()`;
    return evalText(expression);
  };

  const textCount = async (needle) => {
    const expression = `(() => (document.body && document.body.innerText.match(new RegExp(${JSON.stringify(needle)}, 'g')) || []).length)()`;
    return evalText(expression);
  };

  const getValue = async (selector) => {
    const expression = `(() => document.querySelector(${JSON.stringify(selector)})?.value || '')()`;
    return evalText(expression);
  };

  const rowFirstCellByText = async (needle) => {
    const expression = `(() => {
      const rows = Array.from(document.querySelectorAll('table tbody tr'));
      const row = rows.find((tr) => tr.innerText.includes(${JSON.stringify(needle)}));
      if (!row) return '';
      return (row.querySelector('td')?.innerText || '').trim();
    })()`;
    return evalText(expression);
  };

  const rowTextByNeedle = async (needle) => {
    const expression = `(() => {
      const rows = Array.from(document.querySelectorAll('table tbody tr'));
      const row = rows.find((tr) => tr.innerText.includes(${JSON.stringify(needle)}));
      return row ? (row.innerText || '').trim() : '';
    })()`;
    return evalText(expression);
  };

  const postJson = async (url, payload) => {
    const expression = `fetch(${JSON.stringify(url)}, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(${JSON.stringify(payload)}),
      credentials: 'include'
    }).then(async (response) => ({ status: response.status, text: await response.text() }))`;
    const result = await evalText(expression);
    return result;
  };

  const postForm = async (url, fields) => {
    const expression = `fetch(${JSON.stringify(url)}, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(${JSON.stringify(fields)}).toString(),
      credentials: 'include'
    }).then(async (response) => ({ status: response.status, text: await response.text() }))`;
    const result = await evalText(expression);
    return result;
  };

  try {
    await navigate(`${baseUrl}/login`);
    if (!(await textContains('Masuk Sistem'))) fail('Login page did not render');
    await typeInto('input[name="username"]', loginUser);
    await typeInto('input[name="password"]', loginPassword);
    await click('button[type="submit"]');
    await waitFor(() => textContains('Booking Hari Ini'));

    await navigate(`${baseUrl}/dashboard`);
    if (!(await textContains('Status Sistem'))) fail('Dashboard did not render');

    await navigate(`${baseUrl}/bookings`);
    if (!(await textContains('Buat Booking'))) fail('Bookings page did not render');
    const bookingCreate = await postForm('/bookings', {
      action: 'create',
      customer_name: 'Chromium UAT Booking',
      phone: '628123450001',
      vehicle_type: 'Toyota Rush',
      license_plate: 'B1234UAT',
      service_id: '6',
      package_name: '',
      scheduled_start: '2026-09-01T10:00',
      notes: 'chromium uat',
    });
    if (bookingCreate.status !== 200) {
      fail(`Booking create flow returned unexpected status ${bookingCreate.status}`);
    }

    await navigate(`${baseUrl}/bookings`);
    if (!(await textContains('Chromium UAT Booking'))) fail('Created booking not shown in list');

    const invalidBooking = await postForm('/bookings', {
      action: 'create',
      customer_name: '',
      phone: '',
      vehicle_type: '',
      scheduled_start: '2026-09-01',
    });
    if (!String(invalidBooking.text || '').includes('Nama pelanggan dan nomor WhatsApp wajib diisi')) {
      fail('Invalid booking submission did not show the expected validation message');
    }

    await navigate(`${baseUrl}/customers`);
    if (!(await textContains('Manajemen Kontak Customer'))) fail('Customers page did not render');
    const customerCreate = await postForm('/customers', {
      action: 'create',
      name: 'Chromium UAT Customer',
      phone: '628123450002',
      vehicle: 'Honda Brio',
      notes: 'chromium uat',
    });
    if (customerCreate.status !== 200) {
      fail(`Customer create flow returned unexpected status ${customerCreate.status}`);
    }

    await navigate(`${baseUrl}/customers`);
    if (!(await textContains('Chromium UAT Customer'))) fail('Created customer not shown in list');

    await navigate(`${baseUrl}/settings`);
    if (!(await textContains('Settings'))) fail('Settings page did not render');
    const settingsSave = await postForm('/settings', {
      action: 'save',
      daily_capacity: '4',
    });
    if (!String(settingsSave.text || '').includes('Settings berhasil disimpan')) {
      fail('Settings save flow did not return the success message');
    }

    await navigate(`${baseUrl}/templates`);
    if (!(await textContains('Template Pesan WhatsApp'))) fail('Template page did not render');
    const templatesSave = await postForm('/templates', {
      booking_done_template: 'Chromium done {nama}',
      reschedule_template: 'Chromium reschedule {nama}',
      appointment_reminder_template: 'Chromium reminder {nama}',
      maintenance_reminder_template: 'Chromium maintenance {nama}',
      review_request_template: 'Chromium review {nama}',
      google_maps_business_url: 'https://example.com',
    });
    if (!String(templatesSave.text || '').includes('Template berhasil disimpan')) {
      fail('Template save flow did not return the success message');
    }
    await navigate(`${baseUrl}/templates`);
    if (!String(await getValue('input[name="google_maps_business_url"]') || '').includes('example.com')) {
      fail('Template save did not persist the Google Maps URL');
    }
    const templateValue = await getValue('textarea[name="booking_done_template"]');
    if (!String(templateValue || '').includes('Chromium done')) fail('Template save did not persist the booking template');
    const reminderTemplateValue = await getValue('textarea[name="appointment_reminder_template"]');
    if (!String(reminderTemplateValue || '').includes('Chromium reminder')) fail('Template save did not persist the appointment reminder template');

    const rescheduleCreate = await postForm('/bookings', {
      action: 'create',
      customer_name: 'Chromium UAT Reschedule',
      phone: '628123450005',
      vehicle_type: 'Honda Jazz',
      license_plate: 'B1235UAT',
      package_name: '',
      service_id: '6',
      scheduled_start: '2026-09-02T10:00',
      notes: 'chromium reschedule',
    });
    if (rescheduleCreate.status !== 200) {
      fail(`Reschedule booking seed returned unexpected status ${rescheduleCreate.status}`);
    }
    await navigate(`${baseUrl}/bookings`);
    const rescheduleBookingId = await rowFirstCellByText('Chromium UAT Reschedule');
    if (!rescheduleBookingId) fail('Reschedule seed booking not found in list');

    const requestReschedule = await postForm('/bookings', {
      action: 'request_reschedule',
      booking_id: rescheduleBookingId,
      new_scheduled_start: '2026-09-03',
    });
    if (requestReschedule.status !== 200) {
      fail(`Reschedule request returned unexpected status ${requestReschedule.status}`);
    }
    await navigate(`${baseUrl}/reschedule`);
    if (!(await textContains('Chromium UAT Reschedule'))) fail('Requested reschedule not shown in reschedule page');

    const confirmReschedule = await postForm('/reschedule', {
      action: 'confirm_reschedule',
      booking_id: rescheduleBookingId,
      new_scheduled_start: '2026-09-03T10:00',
    });
    if (confirmReschedule.status !== 200) {
      fail(`Reschedule confirm returned unexpected status ${confirmReschedule.status}`);
    }
    await navigate(`${baseUrl}/bookings`);
    const confirmedRescheduleRow = await rowTextByNeedle('Chromium UAT Reschedule');
    if (!confirmedRescheduleRow) fail('Confirmed reschedule booking not shown in bookings page');
    if (!confirmedRescheduleRow.includes('Dikonfirmasi')) {
      fail('Confirmed reschedule booking did not reach Dikonfirmasi status');
    }

    const maintenanceSeed = await postForm('/bookings', {
      action: 'create',
      customer_name: 'Chromium UAT Maintenance',
      phone: '628123450006',
      vehicle_type: 'Toyota Avanza',
      license_plate: 'B1236UAT',
      package_name: 'Coating Premium',
      service_id: '',
      scheduled_start: '2026-09-04T10:00',
      notes: 'chromium maintenance',
    });
    if (maintenanceSeed.status !== 200) {
      fail(`Maintenance seed booking returned unexpected status ${maintenanceSeed.status}`);
    }
    await navigate(`${baseUrl}/bookings`);
    const maintenanceBookingId = await rowFirstCellByText('Chromium UAT Maintenance');
    if (!maintenanceBookingId) fail('Maintenance seed booking not found in list');

    const markComplete = await postForm('/bookings', {
      action: 'update_status',
      booking_id: maintenanceBookingId,
      status: 'selesai',
    });
    if (!String(markComplete.text || '').includes('diperbarui')) {
      fail('Booking completion did not return the expected success message');
    }
    await navigate(`${baseUrl}/maintenance`);
    if (!(await textContains('Chromium UAT Maintenance'))) fail('Maintenance reminder was not generated');

    const reminderId = await rowFirstCellByText('Chromium UAT Maintenance');
    if (!reminderId) fail('Maintenance reminder row not found');

    const sendReminder = await postForm('/maintenance', {
      action: 'send_reminder',
      reminder_id: reminderId,
      message: 'Chromium maintenance reminder',
    });
    if (sendReminder.status !== 200) {
      fail(`Maintenance reminder send returned unexpected status ${sendReminder.status}`);
    }

    const sendReview = await postForm('/maintenance', {
      action: 'send_review',
      reminder_id: reminderId,
      message: 'Chromium review request',
    });
    if (sendReview.status !== 200) {
      fail(`Maintenance review send returned unexpected status ${sendReview.status}`);
    }

    const bookMaintenance = await postForm('/maintenance', {
      action: 'book_maintenance',
      reminder_id: reminderId,
      scheduled_start: '2026-10-04',
    });
    if (bookMaintenance.status !== 200) {
      fail(`Maintenance booking returned unexpected status ${bookMaintenance.status}`);
    }
    await navigate(`${baseUrl}/maintenance`);
    if (!(await textContains('Tidak ada maintenance reminders'))) {
      // The reminder queue may still contain other rows; ensure our item is gone.
      if (await textContains('Chromium UAT Maintenance')) {
        fail('Maintenance booking did not clear the reminder row');
      }
    }

    await navigate(`${baseUrl}/inbox`);
    if (!(await textContains('Inbox WhatsApp'))) fail('Inbox page did not render');

    await navigate(`${baseUrl}/reschedule`);
    if (!(await textContains('Reschedule'))) fail('Reschedule page did not render');

    await navigate(`${baseUrl}/whatsapp-followups`);
    if (!(await textContains('Incomplete Booking'))) fail('Followups page did not render');

    const rejectedInbound = await postJson('/api/whatsapp/inbound', {
      phone: '628123450004',
      text: 'Nama: Chromium Reject\nNo HP: 081234450004\nMerk & Type Mobil: Honda Jazz\nPaket: Coating Premium\nTanggal masuk: 01-09-2026',
      contact_name: 'Chromium Reject',
      chat_id: '628123450004@c.us',
    });
    if (!String(rejectedInbound.text || '').includes('booking_rejected')) {
      fail('Rejected inbound form did not report booking_rejected');
    }

    await navigate(`${baseUrl}/whatsapp-followups`);
    if (!(await textContains('Chromium Reject'))) fail('Rejected inbound customer name not shown in follow-ups');
    if (!(await textContains('Slot penuh untuk hari tersebut'))) fail('Rejected inbound booking reason not shown in follow-ups');

    await navigate(`${baseUrl}/bookings`);
    if (!(await textContains('Booking berhasil dibuat'))) {
      // The success banner is transient, so seeing the created row is the
      // stronger acceptance signal. This check keeps the business flow covered
      // even after the page refresh.
      if (!(await textContains('Chromium UAT Booking'))) fail('Booking acceptance flow did not persist');
    }

    console.log('Chromium UAT passed');
    console.log('- login ok');
    console.log('- dashboard ok');
    console.log('- booking create flow ok');
    console.log('- customer create flow ok');
    console.log('- inbox page ok');
    console.log('- settings page ok');
    console.log('- reschedule page ok');
    console.log('- maintenance page ok');
    console.log('- followups page ok');
    console.log('- invalid booking validation ok');
    console.log('- rejected inbound flow ok');
  } catch (error) {
    fail(error && error.stack ? error.stack : String(error));
  } finally {
    try {
      socket.close();
    } catch {
      // ignore
    }
    chrome.kill('SIGKILL');
    fs.rmSync(userDataDir, { recursive: true, force: true });
  }
}

main();