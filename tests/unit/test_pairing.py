from __future__ import annotations

import pytest
from kreluna_shared.pairing import create_pairing_code, parse_pairing_code


def test_one_paste_pairing_code_round_trip():
    enrollment = "KRELUNA-ENROLL-" + "a" * 43
    code = create_pairing_code(
        director_url="https://director.studio.example/",
        role="pc-fatture",
        display_name="PC-FATTURE",
        enrollment_code=enrollment,
    )

    assert code.startswith("KRELUNA-COLLEGA-1.")
    assert enrollment not in code
    assert parse_pairing_code(code) == {
        "version": 1,
        "director_url": "https://director.studio.example",
        "role": "pc-fatture",
        "display_name": "PC-FATTURE",
        "enrollment_code": enrollment,
    }


@pytest.mark.parametrize(
    "code",
    ["", "KRELUNA-ENROLL-" + "a" * 43, "KRELUNA-COLLEGA-1.not-base64"],
)
def test_pairing_code_rejects_incomplete_or_old_values(code: str):
    with pytest.raises(ValueError, match="collegamento"):
        parse_pairing_code(code)
