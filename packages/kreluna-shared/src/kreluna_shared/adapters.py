from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class DraftResult(BaseModel):
    draft_id: str
    client: str
    net: float
    vat: float
    total: float
    status: str


class ObservedInvoice(BaseModel):
    draft_id: str
    client: str
    net: float
    vat: float
    total: float
    status: str


class SubmitResult(BaseModel):
    draft_id: str
    status: str


class AccountingAdapter(Protocol):
    def prepare_invoice(self, data: dict) -> DraftResult: ...
    def read_invoice(self, draft_id: str) -> ObservedInvoice: ...
    def submit_invoice(self, draft_id: str, approval_token: str) -> SubmitResult: ...
