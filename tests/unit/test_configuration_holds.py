"""Controlli di coerenza: i file di configurazione non devono mai contraddirsi.

Qui si prendono gli errori che non si vedono a occhio: una capability elencata
per un PC ma senza chi la esegue, un rischio non deciso dalla policy, un
portale assegnato a un ruolo che non esiste.
"""

from pathlib import Path

from agent.capabilities import CAPABILITY_ALLOWLIST
from kreluna_shared.agents import load_agent_roles, load_live_agent_roles
from kreluna_shared.capabilities import CAPABILITIES, DENIED_CAPABILITIES
from kreluna_shared.llm import PLANNABLE
from kreluna_shared.policy import load_policy
from kreluna_shared.programs import load_portals, load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_every_job_of_every_pc_has_someone_who_can_do_it():
    for role in load_agent_roles(ROOT / "policies" / "agents.yaml"):
        for capability in role.capabilities:
            assert capability in CAPABILITIES, f"{role.role}: {capability} non è una capability conosciuta"
            assert capability in CAPABILITY_ALLOWLIST, f"{role.role}: {capability} non ha nessuno che la esegue"


def test_every_capability_has_a_risk_decided_by_the_policy():
    engine = load_policy(ROOT / "policies" / "default.yaml")
    for name in CAPABILITIES:
        assert name in engine.config.risk, f"{name} non ha un rischio scritto in default.yaml"


def test_nothing_is_allowed_and_forbidden_at_the_same_time():
    assert not (set(CAPABILITIES) & DENIED_CAPABILITIES)
    assert not (set(PLANNABLE) & DENIED_CAPABILITIES)


def test_the_ai_can_only_plan_things_that_exist():
    for name in PLANNABLE:
        assert name in CAPABILITIES, f"il prompt dell'IA offre {name}, che non esiste"
        assert name in CAPABILITY_ALLOWLIST, f"il prompt dell'IA offre {name}, che nessuno esegue"


def test_the_ai_is_never_offered_the_dangerous_half():
    for forbidden in ("invoice_submit_demo", "payment_prepare"):
        assert forbidden not in PLANNABLE, f"{forbidden} non si propone al modello"


def test_every_portal_belongs_to_a_pc_that_exists():
    live = {role.role for role in load_live_agent_roles()}
    for portal in load_portals():
        assert portal.role in live, f"il portale {portal.key} è di {portal.role}, che non è un PC dello studio"
        assert portal.url.startswith("https://"), f"{portal.key}: indirizzo non sicuro"
        assert portal.field, f"{portal.key}: manca il campo da compilare"
        assert portal.login_note, f"{portal.key}: manca la nota su come si entra"


def test_the_pc_that_owns_a_portal_can_open_and_learn_it():
    from kreluna_shared.agents import capabilities_for_role

    for portal in load_portals():
        caps = capabilities_for_role(portal.role)
        assert "portal_open" in caps, f"{portal.role} ha un portale ma non sa aprirlo"
        assert "portal_learn" in caps, f"{portal.role} ha un portale ma non sa impararlo"


def test_waiting_for_a_login_is_patient_but_not_endless():
    settings = load_settings()
    assert 10 <= settings.wait_for_login_seconds <= 300
    assert 1 <= settings.poll_seconds <= 15
    assert settings.mac_browser


def test_every_live_pc_has_a_job_and_a_program():
    for role in load_live_agent_roles():
        assert role.job and role.job != "Vecchio ruolo", f"{role.role} senza lavoro"
        assert role.program and role.program != "da definire", f"{role.role} senza programma"
        assert role.capabilities, f"{role.role} non sa fare niente"


def test_retired_pcs_are_never_offered_as_a_choice():
    live = load_live_agent_roles()
    assert all(not role.retired for role in live)
    names = [role.role for role in live]
    assert "pc-email" not in names
    assert "pc-pagamenti" not in names
    assert len(names) == len(set(names)), "due PC con lo stesso nome"
