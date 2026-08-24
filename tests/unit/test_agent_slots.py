from pathlib import Path

from kreluna_shared.agents import load_agent_roles
from kreluna_shared.planner import plan_deterministic

ROOT = Path(__file__).resolve().parents[2]


def test_five_studio_agents_exist():
    roles = load_agent_roles(ROOT / "policies" / "agents.yaml")
    names = [role.role for role in roles]
    assert names == ["pc-fatture", "pc-f24", "pc-contabilita", "pc-documenti", "pc-email"]
    assert all(role.program.startswith("da definire") for role in roles)


def test_f24_is_prepare_not_send():
    plan = plan_deterministic("Prepara gli F24 in scadenza, ma non inviarli")
    assert plan.ok
    assert plan.tasks[0].capability == "f24_prepare"
