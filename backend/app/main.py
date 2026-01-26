from fastapi import FastAPI

from .routes.health import router as health_router
from .routes.oauth import router as oauth_router
from .routes.gmail import router as gmail_router
from .routes.calendar import router as calendar_router
from .scheduler import start_scheduler, schedule_gmail_poll, schedule_calendar_checks
from .routes.whatsapp import router as whatsapp_router


app = FastAPI(title="Agenda Agent")

app.include_router(health_router)
app.include_router(oauth_router)
app.include_router(gmail_router)
app.include_router(calendar_router)
app.include_router(whatsapp_router)


@app.on_event("startup")
async def startup():
    start_scheduler()
    schedule_gmail_poll()
    schedule_calendar_checks()


@app.get("/")
async def root():
    return {"status": "ok"}
