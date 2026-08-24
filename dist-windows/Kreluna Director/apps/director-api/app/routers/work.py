from __future__ import annotations

import json
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.deps import Actor, get_actor, get_policy
from app.models import AgentSlot, Approval, AuditEvent, Device, Evidence, InvoiceDraft, Task, as_utc, utcnow
from app.services.audit import write_audit
from app.services.ledger import create_draft, observed_from_draft, verify_invoice
from app.services.orchestrator import dispatch_queued, dispatch_to_device, enqueue_planned
from app.services.registry import hub
from kreluna_shared.crypto import decrypt_bytes
from kreluna_shared.planner import apply_policy, plan_deterministic

router = APIRouter()


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ApprovalDecision(BaseModel):
    note: str | None = None


def _task_out(task: Task, evidence: list[Evidence] | None = None) -> dict[str, Any]:
    return {
        "id": task.id,
        "goal": task.goal,
        "capability": task.capability,
        "args": json.loads(task.args_json),
        "risk": task.risk,
        "status": task.status,
        "needs_approval": task.needs_approval,
        "assigned_device_id": task.assigned_device_id,
        "result": json.loads(task.result_json or "{}"),
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "evidence": [
            {"id": item.id, "kind": item.kind, "sha256": item.sha256, "created_at": item.created_at.isoformat()}
            for item in (evidence or [])
            if item.deleted_at is None
        ],
    }


@router.post("/chat")
async def chat(
    body: ChatBody,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role == "viewer":
        raise HTTPException(status_code=403, detail="Il visore può solo leggere")
    plan = apply_policy(plan_deterministic(body.message), get_policy(), actor.license_state)
    if plan.source == "deterministic-kill":
        from app.services.orchestrator import kill_all

        count = await kill_all(session, actor.tenant_id, actor.user_id)
        await session.commit()
        return {
            "ok": True,
            "summary": f"Ho fermato {count} PC e cancellato i task in corso.",
            "denied": False,
            "tasks": [],
            "source": plan.source,
        }
    if not plan.ok:
        await write_audit(
            session,
            tenant_id=actor.tenant_id,
            actor=actor.user_id,
            action="planner.deny",
            result="deny",
            detail=plan.deny_reason or plan.summary,
        )
        await session.commit()
        return {
            "ok": False,
            "summary": plan.summary,
            "denied": plan.denied,
            "deny_reason": plan.deny_reason,
            "tasks": [],
            "source": plan.source,
        }

    created = []
    for planned in plan.tasks:
        task = await enqueue_planned(
            session,
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            planned=planned,
        )
        created.append(task)
    dispatched = await dispatch_queued(session)
    await session.commit()
    await hub.broadcast_dashboard({"type": "tasks", "tenant_id": actor.tenant_id})
    return {
        "ok": True,
        "summary": plan.summary,
        "denied": False,
        "source": plan.source,
        "tasks": [_task_out(task) for task in created],
        "dispatched": [task.id for task in dispatched],
    }


@router.get("/tasks")
async def list_tasks(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    tasks = (
        await session.execute(
            select(Task).where(Task.tenant_id == actor.tenant_id).order_by(Task.created_at.desc())
        )
    ).scalars().all()
    evidence_rows = (
        await session.execute(select(Evidence).where(Evidence.tenant_id == actor.tenant_id))
    ).scalars().all()
    by_task: dict[str, list[Evidence]] = {}
    for item in evidence_rows:
        by_task.setdefault(item.task_id, []).append(item)
    return {"tasks": [_task_out(task, by_task.get(task.id)) for task in tasks]}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    task = (
        await session.execute(select(Task).where(Task.id == task_id, Task.tenant_id == actor.tenant_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trovato")
    evidence = (
        await session.execute(
            select(Evidence).where(Evidence.task_id == task.id, Evidence.tenant_id == actor.tenant_id)
        )
    ).scalars().all()
    return _task_out(task, list(evidence))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    task = (
        await session.execute(select(Task).where(Task.id == task_id, Task.tenant_id == actor.tenant_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trovato")
    if task.status in {"completed", "cancelled"}:
        return {"ok": True, "status": task.status}
    task.status = "cancelled"
    if task.assigned_device_id:
        await hub.send_agent(task.assigned_device_id, {"type": "kill", "reason": "task_cancel"})
    await session.commit()
    return {"ok": True, "status": "cancelled"}


@router.get("/approvals")
async def list_approvals(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    rows = (
        await session.execute(
            select(Approval)
            .where(Approval.tenant_id == actor.tenant_id)
            .order_by(Approval.created_at.desc())
        )
    ).scalars().all()
    items = []
    for row in rows:
        task = (
            await session.execute(select(Task).where(Task.id == row.task_id, Task.tenant_id == actor.tenant_id))
        ).scalar_one_or_none()
        evidence = (
            await session.execute(
                select(Evidence).where(Evidence.task_id == row.task_id, Evidence.tenant_id == actor.tenant_id)
            )
        ).scalars().all()
        items.append(
            {
                "id": row.id,
                "task_id": row.task_id,
                "action": row.action,
                "status": row.status,
                "preview": json.loads(row.preview_json),
                "expires_at": row.expires_at.isoformat(),
                "task": _task_out(task, list(evidence)) if task else None,
            }
        )
    return {"approvals": items}


@router.post("/approvals/{approval_id}/approve")
async def approve(
    approval_id: str,
    body: ApprovalDecision,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "approver"}:
        raise HTTPException(status_code=403, detail="Solo un approvatore può confermare")
    approval = (
        await session.execute(
            select(Approval).where(Approval.id == approval_id, Approval.tenant_id == actor.tenant_id)
        )
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approvazione non trovata")
    if approval.status != "pending" or approval.token_used:
        raise HTTPException(status_code=409, detail="Token già usato o non più valido")
    if as_utc(approval.expires_at) < utcnow():
        approval.status = "expired"
        await session.commit()
        raise HTTPException(status_code=409, detail="Approvazione scaduta")

    approval.token_used = True
    approval.status = "approved"
    approval.approved_by = actor.user_id
    preview = json.loads(approval.preview_json)
    draft_id = preview.get("draft_id") or (preview.get("observed") or {}).get("draft_id")
    if not draft_id:
        raise HTTPException(status_code=400, detail="Preview senza draft_id")

    from kreluna_shared.models import PlannedTask, Risk

    submit = await enqueue_planned(
        session,
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        planned=PlannedTask(
            goal=f"Emettere fattura demo {draft_id}",
            capability="invoice_submit_demo",
            args={"draft_id": draft_id},
            risk=Risk.HIGH,
            needs_approval=False,
        ),
    )
    submit.status = "queued"
    submit.needs_approval = False
    source_task = (
        await session.execute(select(Task).where(Task.id == approval.task_id, Task.tenant_id == actor.tenant_id))
    ).scalar_one_or_none()
    if source_task and source_task.status == "waiting_approval":
        source_task.status = "completed"
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="approval.approve",
        result="ok",
        task_id=approval.task_id,
        capability=approval.action,
        detail=body.note or "",
    )
    await dispatch_queued(session)
    await session.commit()
    return {"ok": True, "submit_task_id": submit.id}


@router.post("/approvals/{approval_id}/reject")
async def reject(
    approval_id: str,
    body: ApprovalDecision,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "approver"}:
        raise HTTPException(status_code=403, detail="Solo un approvatore può rifiutare")
    approval = (
        await session.execute(
            select(Approval).where(Approval.id == approval_id, Approval.tenant_id == actor.tenant_id)
        )
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approvazione non trovata")
    if approval.status != "pending" or approval.token_used:
        raise HTTPException(status_code=409, detail="Token già usato o non più valido")
    approval.token_used = True
    approval.status = "rejected"
    approval.approved_by = actor.user_id
    task = (
        await session.execute(select(Task).where(Task.id == approval.task_id, Task.tenant_id == actor.tenant_id))
    ).scalar_one()
    task.status = "cancelled"
    task.error = "rejected"
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="approval.reject",
        result="rejected",
        task_id=task.id,
        detail=body.note or "",
    )
    await session.commit()
    return {"ok": True}


@router.get("/evidence/{evidence_id}/image")
async def evidence_image(
    evidence_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if actor.role == "platform_admin":
        raise HTTPException(status_code=403, detail="Il platform admin non vede le evidenze fiscali")
    item = (
        await session.execute(
            select(Evidence).where(Evidence.id == evidence_id, Evidence.tenant_id == actor.tenant_id)
        )
    ).scalar_one_or_none()
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Evidenza non trovata")
    path = settings.evidence_path / item.storage_key
    if not path.exists():
        raise HTTPException(status_code=404, detail="File evidenza assente")
    raw = decrypt_bytes(settings.director_evidence_key, path.read_bytes())
    return Response(content=raw, media_type="image/png")


@router.get("/audit")
async def list_audit(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    rows = (
        await session.execute(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == actor.tenant_id)
            .order_by(AuditEvent.id.desc())
            .limit(100)
        )
    ).scalars().all()
    return {
        "events": [
            {
                "id": row.id,
                "action": row.action,
                "result": row.result,
                "actor": row.actor,
                "task_id": row.task_id,
                "device_id": row.device_id,
                "capability": row.capability,
                "detail": row.detail,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/overview")
async def overview(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    devices = (
        await session.execute(select(Device).where(Device.tenant_id == actor.tenant_id))
    ).scalars().all()
    tasks = (
        await session.execute(select(Task).where(Task.tenant_id == actor.tenant_id))
    ).scalars().all()
    pending = (
        await session.execute(
            select(Approval).where(Approval.tenant_id == actor.tenant_id, Approval.status == "pending")
        )
    ).scalars().all()
    slots = (
        await session.execute(select(AgentSlot).where(AgentSlot.tenant_id == actor.tenant_id))
    ).scalars().all()
    online = sum(1 for device in devices if device.presence in {"online", "busy", "killed"} or device.id in hub.agents)
    return {
        "tenant_id": actor.tenant_id,
        "license_state": actor.license_state,
        "agents_online": online,
        "agents_total": max(len(slots), len(devices)),
        "tasks_today": len(tasks),
        "running": sum(1 for task in tasks if task.status in {"assigned", "running"}),
        "pending_approvals": len(pending),
        "errors": sum(1 for task in tasks if task.status == "failed"),
        "kill_armed": any(device.killed for device in devices),
    }


async def record_invoice_preview(
    session: AsyncSession,
    *,
    tenant_id: str,
    task: Task,
    observed: dict,
    verification: dict,
) -> Approval:
    approval = Approval(
        tenant_id=tenant_id,
        task_id=task.id,
        action="invoice_submit_demo",
        preview_json=json.dumps({"observed": observed, "verification": verification, "draft_id": observed.get("draft_id")}),
        token_nonce="pending",
        expires_at=utcnow() + timedelta(minutes=30),
    )
    session.add(approval)
    task.status = "waiting_approval"
    task.needs_approval = True
    return approval


# used by tests / internal demo without an agent
@router.post("/demo/invoices")
async def demo_prepare_invoice(payload: dict[str, Any], actor: Annotated[Actor, Depends(get_actor)], session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    draft = create_draft(
        actor.tenant_id,
        payload["client_name"],
        payload.get("description", "Consulenza"),
        float(payload["net_eur"]),
        float(payload.get("vat_rate", 0.22)),
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    observed = observed_from_draft(draft)
    expected = {
        "client": draft.client_name,
        "net": draft.net_cents / 100,
        "vat": draft.vat_cents / 100,
        "total": draft.total_cents / 100,
        "status": "draft",
    }
    return {"draft": observed, "verification": verify_invoice(expected, observed)}


@router.post("/demo/invoices/{draft_id}/submit")
async def demo_submit_invoice(draft_id: str, actor: Annotated[Actor, Depends(get_actor)], session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    draft = (
        await session.execute(
            select(InvoiceDraft).where(InvoiceDraft.id == draft_id, InvoiceDraft.tenant_id == actor.tenant_id)
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(status_code=404, detail="Bozza non trovata")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Bozza già emessa")
    draft.status = "issued"
    await session.commit()
    return {"draft": observed_from_draft(draft)}
