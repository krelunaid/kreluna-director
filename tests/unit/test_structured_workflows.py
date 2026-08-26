import pytest
from agent.capabilities.studio import camera, contabilita, contratti, durc, visure
from kreluna_shared.workflows import (
    AccountingPrepareArgs,
    CameraPrepareArgs,
    ContractPrepareArgs,
    DurcPrepareArgs,
    VisurePrepareArgs,
    build_work_draft,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("capability", "args"),
    [
        ("contabilita_prepare", AccountingPrepareArgs(client_name="Andrea Gadducci")),
        ("camera_prepare", CameraPrepareArgs(client_name="Andrea Gadducci", practice_type="variazione sede")),
        ("contratti_prepare", ContractPrepareArgs(client_name="Andrea Gadducci", contract_type="assunzione")),
        ("durc_prepare", DurcPrepareArgs(client_name="Andrea Gadducci")),
        ("visure_prepare", VisurePrepareArgs(client_name="Andrea Gadducci")),
    ],
)
def test_every_studio_workflow_is_review_only(capability, args):
    draft = build_work_draft(capability, args)
    assert draft["ready_for_review"] is True
    assert draft["sent"] is False
    assert draft["submitted"] is False
    assert draft["downloaded"] is False
    assert draft["payment_started"] is False
    assert draft["spid_used"] is False
    assert draft["smart_card_used"] is False
    assert draft["credential_lookup"]["secret_exposed"] is False
    assert draft["requires_human_approval"] is True


def test_practice_and_contract_require_their_exact_type():
    camera_draft = build_work_draft("camera_prepare", CameraPrepareArgs(client_name="Gadducci"))
    contract_draft = build_work_draft("contratti_prepare", ContractPrepareArgs(client_name="Gadducci"))
    assert camera_draft["ready_for_review"] is False
    assert camera_draft["issues"] == ["tipo pratica mancante"]
    assert contract_draft["ready_for_review"] is False
    assert contract_draft["issues"] == ["tipo contratto mancante"]


def test_workflow_enums_reject_unknown_model_values():
    with pytest.raises(ValidationError):
        AccountingPrepareArgs(client_name="Gadducci", operation="invented")
    with pytest.raises(ValidationError):
        VisurePrepareArgs(client_name="Gadducci", visura_type="invented")


@pytest.mark.parametrize(
    "result",
    [
        contabilita(client_name="Gadducci"),
        camera(client_name="Gadducci", practice_type="variazione sede"),
        contratti(client_name="Gadducci", contract_type="assunzione"),
        durc(client_name="Gadducci"),
        visure(client_name="Gadducci"),
    ],
)
def test_agent_returns_a_structured_draft_and_visible_evidence(result):
    assert result["ok"] is True
    assert result["draft"]["kind"] == "operational_draft"
    assert result["evidence"][0]["png"].startswith(b"\x89PNG")
    assert result["sent"] is False
