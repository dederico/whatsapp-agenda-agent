# CLAUDE.md
## Agente Inteligente de Agenda, Comunicaciones y Recordatorios

Este documento describe la arquitectura, objetivos, alcances, decisiones técnicas
y reglas operativas del Agente de Inteligencia Artificial encargado de gestionar
calendario, correos electrónicos, fechas importantes y comunicaciones multicanal
(WhatsApp, email y llamadas).

Este archivo es la referencia principal para cualquier modelo de IA, desarrollador
o sistema automatizado que interactúe con este proyecto.

---

## 1. OBJETIVO DEL SISTEMA

Construir un **Agente Inteligente Personal / Ejecutivo** capaz de:

- Leer, entender y administrar el calendario del usuario.
- Detectar eventos, conflictos y fechas importantes.
- Enviar recordatorios y notificaciones inteligentes.
- Gestionar correos electrónicos (lectura, resumen, borradores y envío controlado).
- Comunicarse por WhatsApp (y eventualmente llamadas telefónicas).
- Operar de forma continua (24/7) en infraestructura cloud.

El sistema debe ser **seguro, auditable, extensible y controlado por reglas**.

---

## 2. PRINCIPIOS DE DISEÑO

1. **Separación de responsabilidades**
   - El cerebro (lógica, reglas, IA) NO se mezcla con el transporte (WhatsApp).
2. **Control humano**
   - Ningún mensaje crítico se envía sin confirmación o regla explícita.
3. **Persistencia y trazabilidad**
   - Todas las acciones deben quedar registradas.
4. **Costo mínimo**
   - Se evita Twilio y proveedores caros.
5. **Escalabilidad futura**
   - Arquitectura lista para múltiples usuarios / cuentas.

---

## 3. ARQUITECTURA GENERAL

### Servicios principales

┌──────────────────────────┐
│ Usuario Final │
│ (WhatsApp / Email / Web) │
└─────────────┬────────────┘
│
▼
┌──────────────────────────┐
│ Agente Inteligente API │
│ (FastAPI) │
│ │
│ - Reglas │
│ - Lógica IA │
│ - Calendario │
│ - Correos │
│ - Scheduler │
└─────────────┬────────────┘
│ HTTP interno
▼
┌──────────────────────────┐
│ Servicio WhatsApp OSS │
│ (Baileys - Node.js) │
│ │
│ - Conexión WhatsApp Web │
│ - Envío de mensajes │
│ - Recepción de mensajes │
└─────────────┬────────────┘
│
▼
WhatsApp Network


---

## 4. SERVICIO WHATSAPP (BAILEYS)

### Tecnología
- Node.js
- Baileys (WhatsApp Web – Open Source)
- Express.js
- Persistent Disk (Render)

### Responsabilidad
- Mantener sesión activa de WhatsApp.
- Enviar mensajes bajo demanda.
- Recibir mensajes entrantes.
- NO contiene lógica de negocio.

### Reglas críticas
- Solo **1 instancia activa** (WhatsApp no permite sesiones paralelas).
- La sesión se guarda en disco persistente (`/var/data`).
- El servicio expone una API HTTP protegida por API Key.

### Endpoints
- `GET /health`
- `GET /qr`
- `POST /send`

---

## 5. AGENTE INTELIGENTE (FASTAPI)

### Responsabilidad
Este servicio es el **cerebro del sistema**.

Funciones:
- Interpretar instrucciones del usuario.
- Leer y escribir Google Calendar.
- Leer, resumir y enviar correos.
- Decidir cuándo y cómo notificar.
- Programar tareas futuras.
- Llamar al servicio WhatsApp.

### Integraciones
- Google Calendar API
- Gmail API
- Servicio WhatsApp (Baileys)
- Base de datos (Postgres)
- Scheduler / Job Queue

---

## 6. MANEJO DE CALENDARIO

Capacidades:
- Leer eventos futuros.
- Crear / modificar / cancelar eventos.
- Detectar conflictos de horario.
- Detectar huecos disponibles.
- Generar resúmenes diarios y semanales.

Regla:
> El agente NO cancela ni reprograma eventos sin autorización explícita.

---

## 7. MANEJO DE CORREOS

Capacidades:
- Leer correos entrantes.
- Detectar urgencia e intención.
- Resumir hilos largos.
- Crear borradores automáticos.
- Enviar correos (con confirmación o regla).

Reglas:
- Envíos automáticos solo a contactos autorizados.
- Seguimientos solo si están definidos en reglas.

---

## 8. NOTIFICACIONES Y RECORDATORIOS

Canales:
- WhatsApp (principal)
- Email
- Llamadas (futuro)

Ejemplos:
- Recordatorios de citas.
- Alertas de conflicto.
- Fechas importantes (cumpleaños, pagos, eventos).
- Resumen diario/matutino.

---

## 9. BASE DE DATOS

### Se almacenan:
- Tokens OAuth cifrados.
- Preferencias del usuario.
- Reglas automáticas.
- Historial de acciones del agente.
- Logs de mensajes enviados.

### NO se almacenan:
- Contraseñas en texto plano.
- Contenido sensible sin cifrado.

---

## 10. SEGURIDAD

- Tokens cifrados.
- API Keys para servicios internos.
- Lista blanca de contactos.
- Logs de auditoría.
- Acciones críticas requieren confirmación.

---

## 11. DESPLIEGUE (RENDER)

Servicios:
- 1 Web Service (FastAPI)
- 1 Web Service (Baileys)
- Persistent Disk para Baileys
- Base de datos Postgres

Restricciones:
- El servicio Baileys **NO se escala horizontalmente**.
- Deploys deben evitar múltiples instancias simultáneas.

---

## 12. FUTURAS EXTENSIONES

- Modo asistente ejecutivo / político.
- Soporte multiusuario.
- Panel web de control.
- Integración con llamadas telefónicas.
- Reglas avanzadas por contexto.
- IA con memoria de largo plazo.

---

## 13. REGLA DE ORO

> El agente **asiste**, no sustituye.
> Toda automatización debe ser explicable, reversible y auditable.

Este documento es la fuente de verdad del sistema.
Cualquier cambio estructural debe reflejarse aquí.
