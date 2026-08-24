from pathlib import Path

from kreluna_shared.agents import load_agent_roles, preferred_role
from kreluna_shared.planner import plan_deterministic

ROOT = Path(__file__).resolve().parents[2]


def test_five_studio_agents_exist():
    roles = load_agent_roles(ROOT / "policies" / "agents.yaml")
    names = [role.role for role in roles]
    assert names == [
        "pc-fatture",
        "pc-pagamenti",
        "pc-f24",
        "pc-contabilita",
        "pc-documenti",
        "pc-email",
    ]
    pagamenti = next(role for role in roles if role.role == "pc-pagamenti")
    assert "payment_prepare" in pagamenti.capabilities
    assert "invoice_check" in pagamenti.capabilities
    assert "invoice_prepare_demo" not in pagamenti.capabilities


def test_f24_is_prepare_not_send():
    plan = plan_deterministic("Prepara gli F24 in scadenza, ma non inviarli")
    assert plan.ok
    assert plan.tasks[0].capability == "f24_prepare"


def test_payments_and_invoice_check_are_split():
    pay = plan_deterministic("Prepara il pagamento di 500 euro, non eseguirlo")
    assert pay.ok
    assert pay.tasks[0].capability == "payment_prepare"
    check = plan_deterministic("Controlla le fatture")
    assert check.ok
    assert check.tasks[0].capability == "invoice_check"
    create = plan_deterministic("Prepara una fattura demo a Rossi per consulenza EUR 1500")
    assert create.tasks[0].capability == "invoice_prepare_demo"
    assert preferred_role("invoice_prepare_demo") == "pc-fatture"
    assert preferred_role("payment_prepare") == "pc-pagamenti"
