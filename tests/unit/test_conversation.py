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


def test_spoken_invoice_separates_account_recipient_typo_and_tax_exemption():
    plan = plan_deterministic(
        "mi fai una fattura per gadduci di mandoperda i 50000 euro a otil Srl "
        "senza iva con dichiarazione d intento"
    )
    assert plan.ok
    task = plan.tasks[0]
    assert task.args["account_name"] == "Andrea Gadducci"
    assert task.args["client_name"] == "Otil SRL"
    assert task.args["description"] == "Manodopera"
    assert task.args["net_eur"] == 50000.0
    assert task.args["vat_rate"] == 0
    assert task.args["vat_note"] == "Dichiarazione d'intento"
    assert "senza IVA" in plan.summary


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


def test_a_note_on_the_open_invoice_does_not_start_over():
    from kreluna_shared.planner import continue_open_invoice

    opened = {"capability": "invoice_prepare_demo", "client_name": "Andrea Gadducci", "net_eur": 5000.0, "description": "Manodopera"}
    note = continue_open_invoice(opened, "esenzione iva con dichiarazione di intento")
    assert note is not None and note.ok
    assert note.tasks == []
    assert "Andrea Gadducci" in note.summary
    assert "5,000" in note.summary or "5000" in note.summary

    same = continue_open_invoice(opened, "in questa fattura")
    assert same is not None and same.ok
    assert "Andrea Gadducci" in same.summary
    assert same.tasks == []

    other = continue_open_invoice(opened, "prepara la visura per Gadducci")
    assert other is None


def test_new_request_clears_every_pending_context():
    from app.services.followup import FollowUps

    memory = FollowUps()
    memory.remember("utente", {"capability": "invoice_prepare_demo"})
    memory.remember_invoice("utente", {"client_name": "Andrea Gadducci"})
    memory.forget_all("utente")

    assert memory.take("utente") is None
    assert memory.last_invoice("utente") is None


def test_invoice_typo_still_keeps_the_client_name():
    plan = plan_deterministic("funzioni mi fai una fattura pae vanni gioitoli")

    assert not plan.ok
    assert plan.source == "deterministic-ask"
    assert plan.pending
    assert plan.pending["client_name"] == "Vanni Gioitoli"
    assert "cliente" not in plan.summary
    assert "importo" in plan.summary
