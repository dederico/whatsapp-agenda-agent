const wppconnect = require('@wppconnect-team/wppconnect');
const fs = require('fs');
const path = require('path');

let client = null;
let lastQr = null;
let tokenFolder = null;

const initWhatsApp = async () => {
  tokenFolder = process.env.WPP_TOKEN_FOLDER || '/var/data/wpp';

  client = await wppconnect.create({
    session: 'agenda-agent',
    catchQR: (base64Qr) => {
      const parts = base64Qr.split(',');
      if (parts.length > 1) {
        lastQr = parts[1];
      }
    },
    statusFind: (statusSession) => {
      if (statusSession === 'isLogged') {
        lastQr = null;
      }
    },
    folderNameToken: tokenFolder,
    headless: true,
    logQR: true,
  });

  client.onMessage(async (message) => {
    if (!message?.body || message?.fromMe) {
      return;
    }
    if (message.isGroupMsg) {
      return;
    }
    const from = message.from?.split('@')[0];
    const text = message.body;
    if (!from || !text) {
      return;
    }
    const backendUrl = process.env.BACKEND_URL;
    if (!backendUrl) {
      return;
    }
    await fetch(`${backendUrl}/whatsapp/incoming`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        from_number: from,
        text,
      }),
    });
  });
};

const sendMessage = async (toNumber, text) => {
  if (!client) {
    throw new Error('WhatsApp not initialized');
  }
  const jid = `${toNumber}@c.us`;
  await client.sendText(jid, text);
};

const getLastQr = () => lastQr;

const clearAuth = () => {
  if (!tokenFolder) {
    return false;
  }
  try {
    fs.rmSync(path.resolve(tokenFolder), { recursive: true, force: true });
    lastQr = null;
    return true;
  } catch {
    return false;
  }
};

module.exports = { initWhatsApp, sendMessage, getLastQr, clearAuth };
