from pathlib import Path

from kreluna_shared.agents import load_agent_roles, load_live_agent_roles, preferred_role
from kreluna_shared.planner import plan_deterministic

ROOT = Path(__file__).resolve().parents[2]


def test_delta_studio_agents_exist():
    roles = load_agent_roles(ROOT / "policies" / "agents.yaml")
    live = load_live_agent_roles(ROOT / "policies" / "agents.yaml")
    names = [role.role for role in roles]
    live_names = [role.role for role in live]
    assert live_names == [
        "pc-fatture",
        "pc-f24",
        "pc-contabilita",
        "pc-camerali",
        "pc-contratti",
        "pc-durc",
        "pc-visure",
    ]
    assert names[-3:] == ["pc-pagamenti", "pc-documenti", "pc-email"]
    fatture = next(role for role in live if role.role == "pc-fatture")
    assert "Webdesk" in fatture.program
    f24 = next(role for role in live if role.role == "pc-f24")
    assert "IPSOA" in f24.program
    assert "Telematico" in f24.program
    contabilita = next(role for role in live if role.role == "pc-contabilita")
    assert "P7M" in contabilita.program or "p7m" in contabilita.program.lower()
    assert "invoice_check" in contabilita.capabilities
    camerali = next(role for role in live if role.role == "pc-camerali")
    assert "CGN" in camerali.program and "ComUnica" in camerali.program
    contratti = next(role for role in live if role.role == "pc-contratti")
    assert "Samuele" in contratti.program
    durc = next(role for role in live if role.role == "pc-durc")
    assert "INPS" in durc.program
    visure = next(role for role in live if role.role == "pc-visure")
    assert visure.program == "Sito CGN"
    pagamenti = next(role for role in roles if role.role == "pc-pagamenti")
    assert pagamenti.retired is True
    assert "invoice_prepare_demo" not in pagamenti.capabilities


def test_f24_is_prepare_not_send():
    plan = plan_deterministic("Prepara gli F24 in scadenza, ma non inviarli")
    assert plan.ok
    assert plan.tasks[0].capability == "f24_prepare"
    assert "IPSOA" in plan.summary
    assert "Telematico" in plan.summary


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
    assert preferred_role("contabilita_prepare") == "pc-contabilita"
    from kreluna_shared.agents import capabilities_for_role
    from agent.mac_boot import enroll_code_for_role

    assert "invoice_prepare_demo" in capabilities_for_role("pc-fatture")
    assert "payment_prepare" not in capabilities_for_role("pc-fatture")
    assert "invoice_prepare_demo" not in capabilities_for_role("pc-pagamenti")
    assert "durc_prepare" in capabilities_for_role("pc-durc")
    assert enroll_code_for_role("pc-fatture") == "KRELUNA-PC-FATTURE"
    assert enroll_code_for_role("pc-durc") == "KRELUNA-PC-DURC"


def test_planner_routes_delta_programs():
    ipsoa = plan_deterministic("Scarica le fatture in IPSOA per Gadducci")
    assert ipsoa.ok
    assert ipsoa.tasks[0].capability == "contabilita_prepare"
    assert ipsoa.tasks[0].args["client_name"] == "Andrea Gadducci"
    assert preferred_role("contabilita_prepare") == "pc-contabilita"

    durc = plan_deterministic("Prepara la richiesta DURC per Gadducci")
    assert durc.tasks[0].capability == "durc_prepare"
    visura = plan_deterministic("Prepara la visura per Gadducci")
    assert visura.tasks[0].capability == "visure_prepare"
    camera = plan_deterministic("Prepara la pratica camerale per Gadducci")
    assert camera.tasks[0].capability == "camera_prepare"
    contratto = plan_deterministic("Prepara il contratto sul sito AdE di Samuele per Gadducci")
    assert contratto.tasks[0].capability == "contratti_prepare"
    fattura = plan_deterministic("mi fai una fattura per gadducci di manodopera")
    assert fattura.tasks[0].capability == "invoice_prepare_demo"
