const extractText = (message) => {
  if (!message) return '';
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    ''
  );
};

let sock = null;

const loadBaileys = async () => {
  const mod = await import('@whiskeysockets/baileys');
  const makeWASocket = mod.default || mod.makeWASocket || mod.default?.makeWASocket;
  const useMultiFileAuthState = mod.useMultiFileAuthState || mod.default?.useMultiFileAuthState;
  const fetchLatestBaileysVersion =
    mod.fetchLatestBaileysVersion || mod.default?.fetchLatestBaileysVersion;

  if (!makeWASocket || !useMultiFileAuthState || !fetchLatestBaileysVersion) {
    throw new Error('Baileys exports not found');
  }
  return { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion };
};

export const initWhatsApp = async () => {
  const { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } =
    await loadBaileys();
  const authPath = process.env.AUTH_PATH || '/var/data/baileys';
  const { state, saveCreds } = await useMultiFileAuthState(authPath);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: true,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('messages.upsert', async (m) => {
    const msg = m.messages?.[0];
    if (!msg || msg.key?.fromMe) {
      return;
    }
    const from = msg.key?.remoteJid?.split('@')[0];
    const text = extractText(msg.message);
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

export const sendMessage = async (toNumber, text) => {
  if (!sock) {
    throw new Error('WhatsApp not initialized');
  }
  const jid = `${toNumber}@s.whatsapp.net`;
  await sock.sendMessage(jid, { text });
};
