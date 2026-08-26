import json

import pytest
from agent.capabilities.f24 import prepare
from kreluna_shared.capabilities import validate_capability_args
from kreluna_shared.f24 import F24PrepareArgs, build_f24_draft
from kreluna_shared.llm import parse_llm_payload
from pydantic import ValidationError


def ordinary_args() -> dict:
    return {
        "client_name": "Andrea Gadducci",
        "form_type": "ordinary",
        "period": "secondo trimestre 2026",
        "lines": [
            {
                "section": "erario",
                "tax_code": "6032",
                "reference_year": "2026",
                "debit_eur": 1250,
            }
        ],
    }


def test_ordinary_draft_is_structured_and_never_sent():
    draft = build_f24_draft(ordinary_args())
    assert draft["form_label"] == "F24 ordinario"
    assert draft["totals"] == {"debit_eur": 1250.0, "credit_eur": 0.0, "balance_eur": 1250.0}
    assert draft["ready_for_review"] is True
    assert draft["sent"] is False
    assert draft["payment_started"] is False
    assert draft["requires_human_approval"] is True


@pytest.mark.parametrize(
    ("form_type", "section", "extra"),
    [
        ("simplified", "imu_locali", {}),
        ("elide", "elide", {"type_code": "R", "identifying_elements": "ABC123"}),
        ("accise", "accise", {"entity_code": "D", "province": "RM"}),
        ("public_entities", "public_entities", {}),
    ],
)
def test_all_supported_form_families(form_type: str, section: str, extra: dict):
    draft = build_f24_draft(
        {
            "client_name": "Cliente Prova",
            "form_type": form_type,
            "lines": [
                {
                    "section": section,
                    "tax_code": "A100",
                    "reference_year": "2026",
                    "debit_eur": 10,
                    **extra,
                }
            ],
        }
    )
    assert draft["ready_for_review"] is True
    assert draft["form_type"] == form_type


def test_incompatible_sections_and_ambiguous_amounts_fail_closed():
    bad_section = ordinary_args()
    bad_section["form_type"] = "elide"
    with pytest.raises(ValidationError, match="sezioni non compatibili"):
        F24PrepareArgs.model_validate(bad_section)

    both = ordinary_args()
    both["lines"][0]["credit_eur"] = 50
    with pytest.raises(ValidationError, match="insieme debito e credito"):
        F24PrepareArgs.model_validate(both)


def test_empty_legacy_request_is_only_a_worksheet():
    draft = build_f24_draft({"period": "in scadenza", "note": "prepara F24"})
    assert draft["ready_for_review"] is False
    assert "righe tributo mancanti" in draft["issues"]
    assert draft["sent"] is False


def test_agent_returns_reviewable_draft_and_keeps_send_disabled():
    result = prepare(**validate_capability_args("f24_prepare", ordinary_args()))
    assert result["ok"] is True
    assert result["draft"]["ready_for_review"] is True
    assert result["sent"] is False
    assert result["payment_started"] is False
    assert "controllo umano" in result["message"]


def test_verified_iva_rule_resolves_code_without_model_memory():
    draft = build_f24_draft(
        {
            "client_name": "Andrea Gadducci",
            "form_type": "ordinary",
            "lines": [
                {
                    "section": "erario",
                    "rule_key": "iva_quarterly_2",
                    "reference_year": "2026",
                    "debit_eur": 1250,
                }
            ],
        }
    )
    assert draft["lines"][0]["tax_code"] == "6032"
    assert draft["rules_source"].startswith("https://www1.agenziaentrate.gov.it/")


def test_unknown_or_conflicting_official_rule_is_rejected():
    args = ordinary_args()
    args["lines"][0]["rule_key"] = "iva_quarterly_2"
    args["lines"][0]["tax_code"] = "6031"
    with pytest.raises(ValidationError, match="conflitto"):
        F24PrepareArgs.model_validate(args)


def test_llm_f24_plan_must_be_grounded_in_operator_text():
    payload = json.dumps(
        {
            "understood": True,
            "summary": "Preparo la bozza F24.",
            "tasks": [
                {
                    "goal": "Preparare F24 per Andrea Gadducci",
                    "capability": "f24_prepare",
                    "args": ordinary_args(),
                }
            ],
        }
    )
    grounded = parse_llm_payload(
        payload,
        "Prepara F24 ordinario per Andrea Gadducci, codice tributo 6032, anno 2026, debito 1.250 euro.",
    )
    assert grounded is not None and grounded.ok

    invented = parse_llm_payload(payload, "Prepara un F24 per Andrea Gadducci")
    assert invented is not None and not invented.ok
    assert "codice tributo" in invented.summary


def test_llm_can_select_only_a_grounded_verified_rule():
    args = ordinary_args()
    args["lines"][0].pop("tax_code")
    args["lines"][0]["rule_key"] = "iva_quarterly_2"
    payload = json.dumps(
        {
            "understood": True,
            "summary": "Preparo la bozza F24 IVA.",
            "tasks": [{"goal": "Preparare F24 IVA", "capability": "f24_prepare", "args": args}],
        }
    )
    plan = parse_llm_payload(
        payload,
        "Prepara F24 ordinario IVA trimestrale secondo trimestre per Andrea Gadducci, anno 2026, debito 1.250 euro.",
    )
    assert plan is not None and plan.ok
    assert plan.tasks[0].args["lines"][0]["rule_key"] == "iva_quarterly_2"

    wrong_period = parse_llm_payload(
        payload,
        "Prepara F24 ordinario IVA trimestrale primo trimestre per Andrea Gadducci, anno 2026, debito 1.250 euro.",
    )
    assert wrong_period is not None and not wrong_period.ok
