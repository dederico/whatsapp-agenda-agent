# whatsapp-agenda-agent

Monorepo for a personal executive assistant:
- `backend/` FastAPI “brain” (rules, calendar, Gmail, scheduler)
- `whatsapp-gateway/` Baileys WhatsApp service
- `shared/` contracts between services

Initial scope: single user, WhatsApp-only control, Gmail/Calendar integrations, full human approval on outbound actions.

  1) Ver estado en vivo (visual)

  - Abre:
    https://agente-agenda-calendario-api.onrender.com/status
  - Ahí verás:
      - Pendientes
      - Eventos recientes (correo nuevo, respuesta enviada, etc.)

  2) WhatsApp (el canal principal)

  - Escanea el QR del gateway cuando haga falta:
    https://agente-agenda-calendario.onrender.com/qr.png
  - Comandos en WhatsApp:
      - ignorar → archiva el correo
      - contestar → abre modo redacción
      - escribe tu respuesta → se genera borrador
      - enviar → envía el correo
      - cancelar → cancela el borrador

  3) Gmail

  - El sistema revisa correos automáticamente (polling).
  - Cuando llega un correo nuevo:
      - Te escribe por WhatsApp:
        “Jefe, recibiste un correo de… Dice lo siguiente…”
  - Tú decides: ignorar o contestar.

  4) OAuth Gmail (autorización)

  - Inicia OAuth:
    https://agente-agenda-calendario-api.onrender.com/oauth/start
  - Te dará una URL → ábrela y autoriza
  - Verifica que quedó autorizado:
    https://agente-agenda-calendario-api.onrender.com/oauth/status

  5) Ver logs en Render

  - Backend: Render → Agente-Agenda-Calendario-Api → Logs
  - Gateway: Render → Agente-Agenda-Calendario → Logs
    Ahí se ve el estado de WhatsApp y errores.

  6) Reset de sesión WhatsApp (si se atora)

  - Ejecuta:

    curl -X POST https://agente-agenda-calendario.onrender.com/reset-auth \
      -H "x-api-key: TU_API_KEY"
  - Luego reinicia el gateway y escanea QR otra vez.

  ———
  