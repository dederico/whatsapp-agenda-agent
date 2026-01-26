const wppconnect = require('@wppconnect-team/wppconnect');
const fs = require('fs');
const path = require('path');

let client = null;
let lastQr = null;
let tokenFolder = null;

const initWhatsApp = async () => {
  tokenFolder = process.env.WPP_TOKEN_FOLDER || '/var/data/wpp';

  const envExec = process.env.PUPPETEER_EXECUTABLE_PATH;
  const executablePath =
    (envExec && isExecutableFile(envExec) ? envExec : undefined) ||
    findChromiumExecutable();
  const useChrome = !executablePath;
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
    autoClose: 0,
    ...(useChrome ? { useChrome: true } : { executablePath }),
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

const findChromiumExecutable = () => {
  const candidates = [
    process.env.PUPPETEER_CACHE_DIR,
    '/opt/render/project/src/whatsapp-gateway/.cache/puppeteer',
    '/opt/render/.cache/puppeteer',
    '/var/data/puppeteer',
  ].filter(Boolean);
  for (const base of candidates) {
    try {
      const chromeDir = path.join(base, 'chrome');
      const platforms = fs
        .readdirSync(chromeDir, { withFileTypes: true })
        .filter((d) => d.isDirectory())
        .map((d) => d.name);
      for (const platform of platforms) {
        const platformDir = path.join(chromeDir, platform);
        const versions = fs
          .readdirSync(platformDir, { withFileTypes: true })
          .filter((d) => d.isDirectory())
          .map((d) => d.name);
        for (const version of versions) {
          const execPath = path.join(
            platformDir,
            version,
            'chrome-linux64',
            'chrome'
          );
          if (fs.existsSync(execPath)) {
            return execPath;
          }
        }
      }
    } catch {
      // ignore
    }
  }
  return undefined;
};

const isExecutableFile = (filePath) => {
  try {
    const stat = fs.statSync(filePath);
    return stat.isFile();
  } catch {
    return false;
  }
};

module.exports = { initWhatsApp, sendMessage, getLastQr, clearAuth };
