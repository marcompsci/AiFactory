"""The team roster (V6.24) and the records export (V6.26). Both are owner-only: the roster holds sign-in emails, and
the export is a copy of the organization's records."""
from __future__ import annotations

import json
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from services.api.finance import owner
from services.core import db
from services.core.auth import Principal
from services.core.events import emit, transaction

router = APIRouter(prefix="/api")

EXPORT_EVERY = 60.0  # seconds between exports per person: an export reads a lot
_last_export: dict[str, float] = {}
_lock = threading.Lock()


@router.get("/team")
def team(p: Principal = Depends(owner)) -> dict:
    from services.core.roster import team as build
    with db.get_engine().connect() as conn:
        return build(conn, p.organization_id, p.user_id)


@router.get("/export")
def export(p: Principal = Depends(owner)) -> Response:
    from services.management.export import build
    now = time.monotonic()
    with _lock:
        last = _last_export.get(p.user_id)
        if last is not None and now - last < EXPORT_EVERY:
            raise HTTPException(429, f"one export a minute; try again in {int(EXPORT_EVERY - (now - last)) + 1} s")
        _last_export[p.user_id] = now
    with db.get_engine().connect() as conn:
        bundle = build(conn, p.organization_id, p.user_id)
    with transaction() as conn:
        emit(conn, "records.exported", org_id=p.organization_id,
             payload={"by": p.user_id, "missions": bundle["limits"]["missions_included"], "events": bundle["limits"]["events_included"],
                      "bundle_sha256": bundle["bundle_sha256"], "audit_ok": bundle["audit"]["ok"]})
    name = f"aiciv-records-{bundle['generated_at'][:10]}.json"
    return Response(json.dumps(bundle, default=str, ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
