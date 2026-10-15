"""Company knowledge base API: members read; the owner and admins add, edit, upload and delete."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.events import emit, transaction
from services.finance import audit
from services.finance.permissions import require_finance
from services.knowledge import kb

router = APIRouter(prefix="/api/knowledge")


def member(request: Request) -> Principal:
    return authenticate(request)


def editor(request: Request) -> Principal:
    p = authenticate(request)
    require_finance(p)  # owner or admin
    mutation_limiter.check(p.user_id)
    return p


class DocIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=kb.MAX_BODY)
    company: str = Field(default="shared", pattern="^(phoronomics|phoronomic_studios|shared)$")
    kind: str = Field(default="doc", pattern="^(doc|skill)$")
    description: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    slug: str | None = Field(default=None, max_length=80)


def _changed(conn, p: Principal, action: str, slug: str, title: str) -> None:
    audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action=f"knowledge.{action}",
                 subject_type="knowledge", subject_id=None, detail={"slug": slug, "title": title[:120]})
    emit(conn, "knowledge.updated", payload={"action": action, "slug": slug, "title": title[:120]})


@router.get("")
def listing(company: str | None = None, kind: str | None = None, q: str = "", p: Principal = Depends(member)):
    with db.get_engine().connect() as conn:
        items = kb.listing(conn, p.organization_id, company if company in kb.COMPANIES else None, kind if kind in kb.KINDS else None, q[:200])
    return {"companies": [{"id": k, "name": v} for k, v in kb.COMPANIES.items()], "items": items,
            "counts": {"doc": sum(1 for i in items if i["kind"] == "doc"), "skill": sum(1 for i in items if i["kind"] == "skill")},
            "can_edit": p.role in ("owner", "admin")}


@router.put("/upload", status_code=201)
async def upload(request: Request, filename: str, company: str = "shared", kind: str = "auto", p: Principal = Depends(editor)):
    """One Markdown or text file as the request body. A SKILL.md (or any file with a name/description header) is a skill."""
    if company not in kb.COMPANIES:
        raise HTTPException(status_code=422, detail="unknown company")
    name = filename.replace("\\", "/")[:200]
    if not name.lower().endswith((".md", ".markdown", ".txt")):
        raise HTTPException(status_code=415, detail=f"{name}: only .md and .txt files")
    raw = await request.body()
    if len(raw) > kb.MAX_BODY:
        raise HTTPException(status_code=413, detail=f"{name} is larger than 400 KB")
    text = raw.decode("utf-8", "replace")
    item = kb.from_markdown(text, name)
    if kind in kb.KINDS:
        item["kind"] = kind
    with transaction() as conn:
        slug, _ = kb.upsert(conn, p.organization_id, title=item["title"], body=text, company=company, kind=item["kind"],
                            description=item["description"], slug=item["slug"], source="upload", user_id=p.user_id,
                            tags=["skill"] if item["kind"] == "skill" else [])
        _changed(conn, p, "uploaded", slug, item["title"])
    return {"slug": slug, "title": item["title"], "kind": item["kind"]}


@router.get("/{slug}")
def read(slug: str, p: Principal = Depends(member)):
    with db.get_engine().connect() as conn:
        r = kb.get(conn, p.organization_id, kb.slugify(slug))
    if r is None:
        raise HTTPException(status_code=404, detail="not in the knowledge base")
    return kb.view(r, full=True)


@router.post("", status_code=201)
def create(body: DocIn, p: Principal = Depends(editor)):
    with transaction() as conn:
        slug = kb.slugify(body.slug or body.title)
        if kb.get(conn, p.organization_id, slug):
            raise HTTPException(status_code=409, detail="an entry with that name exists; edit it instead")
        slug, _ = kb.upsert(conn, p.organization_id, title=body.title, body=body.body, company=body.company, kind=body.kind,
                            description=body.description, tags=body.tags, slug=slug, user_id=p.user_id)
        _changed(conn, p, "added", slug, body.title)
    return {"slug": slug}


@router.put("/{slug}")
def edit(slug: str, body: DocIn, p: Principal = Depends(editor)):
    with transaction() as conn:
        if kb.get(conn, p.organization_id, kb.slugify(slug)) is None:
            raise HTTPException(status_code=404, detail="not in the knowledge base")
        kb.upsert(conn, p.organization_id, title=body.title, body=body.body, company=body.company, kind=body.kind,
                  description=body.description, tags=body.tags, slug=kb.slugify(slug), user_id=p.user_id)
        _changed(conn, p, "edited", kb.slugify(slug), body.title)
    return {"slug": kb.slugify(slug)}


@router.delete("/{slug}")
def remove(slug: str, p: Principal = Depends(editor)):
    with transaction() as conn:
        r = kb.get(conn, p.organization_id, kb.slugify(slug))
        if r is None:
            raise HTTPException(status_code=404, detail="not in the knowledge base")
        conn.execute(db.kb_documents.delete().where(db.kb_documents.c.id == r.id))
        _changed(conn, p, "removed", r.slug, r.title)
    return {"slug": r.slug, "removed": True}
