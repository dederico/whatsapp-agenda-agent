# whatsapp-agenda-agent

Monorepo for a personal executive assistant:
- `backend/` FastAPI “brain” (rules, calendar, Gmail, scheduler)
- `whatsapp-gateway/` Baileys WhatsApp service
- `shared/` contracts between services

Initial scope: single user, WhatsApp-only control, Gmail/Calendar integrations, full human approval on outbound actions.
