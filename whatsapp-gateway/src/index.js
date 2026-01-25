const { config } = require('dotenv');
const Hapi = require('@hapi/hapi');
const QRCode = require('qrcode');
const { initWhatsApp, sendMessage, getLastQr, clearAuth } = require('./whatsapp');

config();

const server = Hapi.server({
  port: process.env.PORT || 3001,
  host: '0.0.0.0',
});

server.route({
  method: 'GET',
  path: '/health',
  handler: () => ({ status: 'ok' }),
});

server.route({
  method: 'GET',
  path: '/qr',
  handler: () => ({ qr: getLastQr() }),
});

server.route({
  method: 'GET',
  path: '/qr.png',
  handler: async (_request, h) => {
    const qr = getLastQr();
    if (!qr) {
      return h.response('no-qr').code(404);
    }
    const png = await QRCode.toBuffer(qr, { type: 'png' });
    return h.response(png).type('image/png');
  },
});

server.route({
  method: 'POST',
  path: '/send',
  handler: async (request) => {
    const apiKey = request.headers['x-api-key'];
    if (!apiKey || apiKey !== process.env.API_KEY) {
      return { error: 'unauthorized' };
    }

    const { to_number, text } = request.payload;
    await sendMessage(to_number, text);
    return { status: 'sent' };
  },
});

server.route({
  method: 'POST',
  path: '/reset-auth',
  handler: async (request) => {
    const apiKey = request.headers['x-api-key'];
    if (!apiKey || apiKey !== process.env.API_KEY) {
      return { error: 'unauthorized' };
    }
    const ok = clearAuth();
    return { status: ok ? 'cleared' : 'failed' };
  },
});

const start = async () => {
  await initWhatsApp();
  await server.start();
  console.log(`WhatsApp gateway running on ${server.info.uri}`);
};

start();
