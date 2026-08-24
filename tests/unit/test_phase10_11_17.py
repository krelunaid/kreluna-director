from agent.tools.automation import prefer_method, safe_click
from agent.tools.bounds import Bounds
from agent.tools.vision_loop import ScreenObservation, run_loop, unexpected_dialog
from kreluna_shared.adapters import DraftResult


def test_method_order_prefers_api():
    assert prefer_method(["mouse", "api", "playwright"]) == "api"


def test_mouse_outside_bounds_denied():
    try:
        safe_click(10, 10, Bounds(100, 100, 50, 50))
        assert False
    except PermissionError as exc:
        assert "OUTSIDE_ALLOWED_REGION" in str(exc)


def test_vision_blocks_unexpected_dialog():
    def capture():
        return ScreenObservation(window_title="UAC", extracted_text=["Controllo dell'account utente"], confidence=0.9)

    result = run_loop(capture=capture, act=lambda _o: "click", verify=lambda _o: False, max_steps=3)
    assert result.status == "blocked"
    assert unexpected_dialog(capture()) is True


def test_vision_timeout():
    def capture():
        return ScreenObservation(window_title="Demo", extracted_text=["ok"], confidence=0.9)

    result = run_loop(capture=capture, act=lambda _o: "noop", verify=lambda _o: False, max_steps=2)
    assert result.status == "timeout"
    assert result.steps == 2


def test_sandbox_adapter_contract():
    draft = DraftResult(draft_id="1", client="Rossi", net=1500, vat=330, total=1830, status="draft")
    assert draft.status == "draft"
