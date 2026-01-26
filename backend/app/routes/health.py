from fastapi import APIRouter

from ..state import state

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/status")
async def status():
    pending_count = len(state.pending_by_user)
    events = list(state.events)[:50]
    html = [
        "<html><head><title>Agenda Agent Status</title>",
        "<style>body{font-family:Arial,sans-serif;padding:20px;} .tag{font-size:12px;color:#666;} .evt{margin:6px 0;}</style>",
        "</head><body>",
        "<h1>Agenda Agent Status</h1>",
        f"<p>Pending items: <b>{pending_count}</b></p>",
        "<h2>Latest Events</h2>",
    ]
    if not events:
        html.append("<p class='tag'>No events yet.</p>")
    else:
        html.append("<div>")
        for ev in events:
            html.append(
                f\"<div class='evt'><span class='tag'>{ev['ts']} · {ev['kind']}</span><br/>{ev['detail']}</div>\"
            )
        html.append("</div>")
    html.append("</body></html>")
    return "".join(html)
