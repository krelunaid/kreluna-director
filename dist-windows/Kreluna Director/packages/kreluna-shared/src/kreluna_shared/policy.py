from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from kreluna_shared.capabilities import APPROVAL_CAPABILITIES, DENIED_CAPABILITIES
from kreluna_shared.models import LicenseState, PolicyDecision, Risk


class PolicyConfig(BaseModel):
    risk: dict[str, Risk] = Field(default_factory=dict)
    approval_required: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    screenshot: dict[str, Any] = Field(default_factory=dict)
    license: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    decision: PolicyDecision
    capability: str
    risk: Risk
    reason: str
    license_state: LicenseState


class PolicyEngine:
    """Policy is the authority. The model never overrides deny/approval."""

    def __init__(self, config: PolicyConfig):
        self.config = config
        deny = set(DENIED_CAPABILITIES)
        deny.update(config.deny)
        self._deny = frozenset(deny)
        approval = set(APPROVAL_CAPABILITIES)
        approval.update(config.approval_required)
        self._approval = frozenset(approval)

    def risk_for(self, capability: str, fallback: Risk = Risk.MEDIUM) -> Risk:
        raw = self.config.risk.get(capability)
        if raw is not None:
            return Risk(raw) if not isinstance(raw, Risk) else raw
        return fallback

    def decide(self, capability: str, license_state: LicenseState | str) -> Decision:
        state = LicenseState(license_state)
        risk = self.risk_for(capability)
        if state in {LicenseState.SUSPENDED, LicenseState.TERMINATED}:
            return Decision(
                decision=PolicyDecision.DENY_LICENSE,
                capability=capability,
                risk=risk,
                reason="Licenza non attiva: nessun nuovo task operativo.",
                license_state=state,
            )
        if capability in self._deny:
            return Decision(
                decision=PolicyDecision.DENY,
                capability=capability,
                risk=risk,
                reason="Capability vietata dalla policy di sicurezza.",
                license_state=state,
            )
        if capability in self._approval or risk in {Risk.HIGH, Risk.CRITICAL}:
            return Decision(
                decision=PolicyDecision.APPROVAL,
                capability=capability,
                risk=risk,
                reason="Azione sensibile: serve approvazione umana separata.",
                license_state=state,
            )
        return Decision(
            decision=PolicyDecision.ALLOW,
            capability=capability,
            risk=risk,
            reason="Azione consentita dalla policy.",
            license_state=state,
        )


def load_policy(path: str | Path) -> PolicyEngine:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Policy YAML must be a mapping")
    config = PolicyConfig.model_validate(raw)
    return PolicyEngine(config)


def parse_policy_yaml(text: str) -> PolicyEngine:
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("Policy YAML must be a mapping")
    return PolicyEngine(PolicyConfig.model_validate(raw))
