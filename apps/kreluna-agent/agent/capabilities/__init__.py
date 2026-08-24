from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agent.capabilities import (
    documents,
    email_draft,
    f24,
    invoice_demo,
    notepad,
    payments,
    portal,
    studio,
)

Handler = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]

CAPABILITY_ALLOWLIST: dict[str, Handler] = {
    "notepad_write": notepad.write_notepad,
    "invoice_prepare_demo": invoice_demo.prepare,
    "invoice_submit_demo": invoice_demo.submit,
    "document_check": documents.check,
    "email_draft": email_draft.draft,
    "f24_prepare": f24.prepare,
    "contabilita_prepare": studio.contabilita,
    "camera_prepare": studio.camera,
    "contratti_prepare": studio.contratti,
    "durc_prepare": studio.durc,
    "visure_prepare": studio.visure,
    "portal_open": portal.open_portal,
    "payment_prepare": payments.prepare,
    "invoice_check": payments.check_invoices,
}
