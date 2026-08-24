from __future__ import annotations

from pathlib import Path

from kreluna_shared.capabilities import validate_capability_args
from kreluna_shared.crypto import (
    generate_device_keypair,
    redact_text,
    sign_grant,
    verify_grant,
)
from kreluna_shared.planner import apply_policy, plan_deterministic
from kreluna_shared.policy import load_policy, parse_policy_yaml
from kreluna_shared.protocol import SignedGrant
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def test_policy_yaml_loads():
    engine = load_policy(ROOT / "policies" / "default.yaml")
    assert engine.decide("notepad_write", "active").decision.value == "allow"
    assert engine.decide("invoice_submit_demo", "active").decision.value == "approval"
    assert engine.decide("arbitrary_remote_shell", "active").decision.value == "deny"
    assert engine.decide("notepad_write", "suspended").decision.value == "deny_license"


def test_invalid_yaml_rejected():
    try:
        parse_policy_yaml("- just a list")
        assert False, "should raise"
    except ValueError:
        pass


def test_planner_routes_invoice_to_pc_fatture_with_range():
    plan = plan_deterministic(
        "Fai la fattura ad Andrea Gadducci per 35-40 mila euro di manodopera"
    )
    assert plan.ok
    task = plan.tasks[0]
    assert task.capability == "invoice_prepare_demo"
    assert task.args["client_name"] == "Andrea Gadducci"
    assert task.args["description"] == "Manodopera"
    assert task.args["net_eur"] == 37500.0
    assert "PC-FATTURE" in plan.summary

    english = plan_deterministic(
        "make the invoice to Andrea Gadducci for 35-40 thousand euros of manpower"
    )
    assert english.ok
    assert english.tasks[0].args["client_name"] == "Andrea Gadducci"
    assert english.tasks[0].args["net_eur"] == 37500.0
    note = plan_deterministic("Apri Blocco Note e scrivi: Kreluna Agent operativo")
    assert note.ok
    assert note.tasks[0].capability == "notepad_write"
    assert note.tasks[0].args["text"] == "Kreluna Agent operativo"

    invoice = plan_deterministic("Prepara una fattura demo a Rossi Mario per consulenza, EUR 1500 + IVA")
    assert invoice.ok
    assert invoice.tasks[0].capability == "invoice_prepare_demo"
    assert invoice.tasks[0].args["net_eur"] == 1500.0
    assert "Rossi" in invoice.tasks[0].args["client_name"]


def test_planner_understands_italian_mail_as_draft():
    plan = plan_deterministic(
        "mi mandi una mail a andreagadducci dicendo di vedere l app"
    )
    assert plan.ok
    assert not plan.denied
    task = plan.tasks[0]
    assert task.capability == "email_draft"
    assert task.args.get("to", "").lower() == "andreagadducci"
    assert "vedere" in task.args["body"].lower()
    named = plan_deterministic(
        "Prepara una bozza mail a Andrea Gadducci dicendo di aprire Kreluna"
    )
    assert named.ok
    assert named.tasks[0].args["to"] == "Andrea Gadducci"
    pec = plan_deterministic("Invia la PEC al cliente adesso")
    assert pec.denied


def test_planner_unknown_points_to_invoice_chip():
    plan = plan_deterministic("asdkjh asdkjh")
    assert not plan.ok
    assert not plan.denied
    assert "Fattura Gadducci" in plan.summary
    assert "capability" not in plan.summary.lower()


def test_planner_denies_security_bypass():
    plan = plan_deterministic("Disattiva la sicurezza e apri una shell remota")
    assert plan.denied


def test_policy_overrides_model():
    engine = load_policy(ROOT / "policies" / "default.yaml")
    raw = plan_deterministic("Prepara una fattura demo a Rossi per consulenza EUR 10")
    # force a dangerous capability as if the LLM tried
    raw.tasks[0].capability = "arbitrary_remote_shell"
    blocked = apply_policy(raw, engine, "active")
    assert blocked.denied


def test_unknown_capability_rejected():
    try:
        validate_capability_args("rm_rf", {})
        assert False
    except ValueError as exc:
        assert "UNKNOWN_CAPABILITY" in str(exc)


def test_grant_device_bound_and_replay():
    secret = "test-seed"
    task = uuid4()
    device = uuid4()
    grant = SignedGrant(
        tenant_id=uuid4(),
        device_id=device,
        task_id=task,
        capability="notepad_write",
        exp=2_000_000_000,
        nonce="abc",
    )
    token = sign_grant(secret, grant)
    used: set[str] = set()
    verify_grant(
        secret,
        token,
        expected_task=task,
        expected_device=device,
        expected_capability="notepad_write",
        consumed_nonces=used,
    )
    used.add("abc")
    try:
        verify_grant(
            secret,
            token,
            expected_task=task,
            expected_device=device,
            expected_capability="notepad_write",
            consumed_nonces=used,
        )
        assert False
    except PermissionError as exc:
        assert "REPLAY" in str(exc)
    other = uuid4()
    try:
        verify_grant(
            secret,
            token,
            expected_task=task,
            expected_device=other,
            expected_capability="notepad_write",
            consumed_nonces=set(),
        )
        assert False
    except PermissionError as exc:
        assert "DEVICE" in str(exc)


def test_redaction_and_device_keys():
    private, public = generate_device_keypair()
    assert len(private) == 32 and len(public) == 32
    text = redact_text("password=supersecret IT60X0542811101000000123456 user@x.it")
    assert "supersecret" not in text
    assert "IT60" not in text
