"""Run again (V6.21) and follow-on missions (V6.22): services/management/links.py. Starting work needs the operator
role, the same as starting a mission; anyone signed in can see a mission's links."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.core import db
from services.core.auth import Principal, authenticate
from services.management import links

router = APIRouter(prefix="/api")


def member(request: Request) -> Principal:
    return authenticate(request)


def operator(request: Request) -> Principal:
    p = authenticate(request)
    p.require("operator")
    return p


class RerunIn(BaseModel):
    priority: str | None = Field(default=None, pattern="^(urgent|normal|low)$")


class FollowupIn(BaseModel):
    kind: str = Field(pattern="^(fix_failing_test|run_tests|market_research)$")
    prompt: str | None = Field(default=None, max_length=4000)
    params: dict = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=120)
    priority: str = Field(default="normal", pattern="^(urgent|normal|low)$")


RUN_TESTS_PROMPT = "Run the test suite of the connected repository and report which tests fail."


def _err(exc: links.LinkError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.post("/missions/{mission_id}/rerun", status_code=201)
def rerun(mission_id: str, body: RerunIn | None = None, p: Principal = Depends(operator)) -> dict:
    try:
        return links.rerun(mission_id, p, (body.priority if body else None))
    except links.LinkError as exc:
        raise _err(exc) from exc


@router.post("/missions/{mission_id}/followups", status_code=201)
def add_followup(mission_id: str, body: FollowupIn, p: Principal = Depends(operator)) -> dict:
    spec = body.model_dump(exclude={"priority"})
    if body.kind == "run_tests" and not body.prompt:
        spec["prompt"] = RUN_TESTS_PROMPT
    try:
        return links.add_followup(mission_id, p, spec, body.priority)
    except links.LinkError as exc:
        raise _err(exc) from exc


@router.get("/missions/{mission_id}/links")
def mission_links(mission_id: str, p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        try:
            links._mission(conn, p.organization_id, mission_id)
        except links.LinkError as exc:
            raise _err(exc) from exc
        return links.for_mission(conn, p.organization_id, mission_id)


@router.delete("/followups/{link_id}")
def cancel_followup(link_id: str, p: Principal = Depends(operator)) -> dict:
    try:
        return links.cancel_followup(p.organization_id, link_id, p.user_id)
    except links.LinkError as exc:
        raise _err(exc) from exc
