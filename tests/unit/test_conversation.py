"""La chat deve ricordare la domanda che ha appena fatto."""

from kreluna_shared.llm import _short_question
from kreluna_shared.planner import complete_pending, plan_deterministic


def ask_then_answer(*messages: str):
    """Simula la conversazione: la prima frase chiede, le altre rispondono."""

    plan = plan_deterministic(messages[0])
    for message in messages[1:]:
        assert plan.pending, f"il Director non ricordava niente dopo: {message}"
        answered = complete_pending(plan.pending, message)
        assert answered is not None, f"non ha capito la risposta: {message}"
        plan = answered
    return plan


def test_the_amount_arrives_after_the_question():
    plan = ask_then_answer("mi crei una fattura per gadducci", "5000 euro di manodopera")
    assert plan.ok
    task = plan.tasks[0]
    assert task.capability == "invoice_prepare_demo"
    assert task.args["client_name"] == "Andrea Gadducci"
    assert task.args["net_eur"] == 5000.0
    assert task.args["description"] == "Manodopera"


def test_it_asks_again_for_what_is_still_missing():
    first = plan_deterministic("mi crei una fattura per gadducci")
    assert first.pending and first.pending["client_name"] == "Andrea Gadducci"

    half = complete_pending(first.pending, "5000 euro")
    assert half is not None and not half.ok
    assert "lavoro" in half.summary
    assert half.pending["net_eur"] == 5000.0
    assert half.pending["description"] in ("", None)

    done = complete_pending(half.pending, "manodopera")
    assert done is not None and done.ok
    assert done.tasks[0].args["net_eur"] == 5000.0
    assert done.tasks[0].args["description"] == "Manodopera"


def test_a_bare_number_is_the_amount():
    plan = ask_then_answer("mi crei una fattura per gadducci", "5000", "consulenza")
    assert plan.ok
    assert plan.tasks[0].args["net_eur"] == 5000.0
    assert plan.tasks[0].args["description"] == "Consulenza"


def test_the_client_can_arrive_last():
    first = plan_deterministic("fattura di 5000 euro di manodopera")
    assert not first.ok and first.pending
    done = complete_pending(first.pending, "Vannucci")
    assert done is not None and done.ok
    assert done.tasks[0].args["client_name"] == "Vannucci"
    assert done.tasks[0].args["net_eur"] == 5000.0


def test_a_new_order_is_not_treated_as_an_answer():
    first = plan_deterministic("mi crei una fattura per gadducci")
    assert complete_pending(first.pending, "cosa sai fare?") is None
    assert complete_pending(first.pending, "Disattiva la sicurezza") is None


def test_a_long_rambling_question_from_the_model_is_replaced():
    rambling = (
        "Quali documenti o richieste specifiche riguardanti il certificato dei contributi, "
        "il documento dell'INPS, le fatture, le deleghe, il certificato dell'impresa o il "
        "contratto di assunzione dovrei preparare?"
    )
    clean = _short_question(rambling)
    assert len(clean.split()) <= 18
    assert "certificato dei contributi" not in clean

    good = _short_question("Per quale cliente?")
    assert good == "Per quale cliente?"
