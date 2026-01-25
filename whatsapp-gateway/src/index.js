const { config } = require('dotenv');
const Hapi = require('@hapi/hapi');
const { initWhatsApp, sendMessage, getLastQr } = require('./whatsapp');

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

const start = async () => {
  await initWhatsApp();
  await server.start();
  console.log(`WhatsApp gateway running on ${server.info.uri}`);
};

start();
