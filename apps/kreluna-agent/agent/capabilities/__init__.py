from __future__ import annotations

from typing import Any, Awaitable, Callable

from agent.capabilities import documents, email_draft, invoice_demo, notepad

Handler = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]

CAPABILITY_ALLOWLIST: dict[str, Handler] = {
    "notepad_write": notepad.write_notepad,
    "invoice_prepare_demo": invoice_demo.prepare,
    "invoice_submit_demo": invoice_demo.submit,
    "document_check": documents.check,
    "email_draft": email_draft.draft,
}
