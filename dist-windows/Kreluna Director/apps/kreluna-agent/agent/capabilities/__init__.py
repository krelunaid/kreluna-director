from __future__ import annotations

from typing import Any, Awaitable, Callable

from agent.capabilities import documents, email_draft, f24, invoice_demo, notepad, payments

Handler = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]

CAPABILITY_ALLOWLIST: dict[str, Handler] = {
    "notepad_write": notepad.write_notepad,
    "invoice_prepare_demo": invoice_demo.prepare,
    "invoice_submit_demo": invoice_demo.submit,
    "document_check": documents.check,
    "email_draft": email_draft.draft,
    "f24_prepare": f24.prepare,
    "payment_prepare": payments.prepare,
    "invoice_check": payments.check_invoices,
}
