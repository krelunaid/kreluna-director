from __future__ import annotations

import pytest
from app.models import ClientCredential
from app.services.vault import (
    VaultImportError,
    decrypt_credential,
    encrypt_credential_fields,
    mask_username,
    parse_credentials_csv,
)
from cryptography.exceptions import InvalidTag


def test_csv_is_recognized_locally_without_returning_secrets() -> None:
    rows, warnings = parse_credentials_csv(
        b"cliente;portale;username;password;tipo_segreto;etichetta\n"
        b"Andrea Gadducci;webdesk;andrea@example.it;Segreto-123;password;principale\n"
        b"Bianchi SRL;CGN;studio-bianchi;Token-456;api_token;visure\n"
    )

    assert warnings == []
    assert len(rows) == 2
    assert rows[0].portal == "webdesk"
    public = rows[0].public()
    assert public["username_masked"].startswith("an")
    assert "Segreto-123" not in str(public)


def test_csv_refuses_spid_cns_and_missing_columns() -> None:
    with pytest.raises(VaultImportError, match="SPID"):
        parse_credentials_csv(b"cliente;portale;username;password\nRossi;SPID;mario;segreto\n")
    with pytest.raises(VaultImportError, match="Colonne mancanti"):
        parse_credentials_csv(b"cliente;username\nRossi;mario\n")


def test_csv_refuses_template_placeholder() -> None:
    with pytest.raises(VaultImportError, match="valore di esempio"):
        parse_credentials_csv(
            b"cliente;portale;username;password\nRossi;webdesk;mario;SOSTITUISCI\n"
        )


def test_credentials_are_context_bound_and_masked() -> None:
    row = ClientCredential(
        tenant_id="tenant-a",
        client_name="Cliente A",
        client_key="cliente-a",
        portal="webdesk",
        credential_label="principale",
        secret_kind="password",
        username_ciphertext="",
        secret_ciphertext="",
        updated_by="owner",
    )
    encrypt_credential_fields(row, username="cliente@example.it", secret="Segreto Molto Forte")

    assert "cliente@example.it" not in row.username_ciphertext
    assert "Segreto Molto Forte" not in row.secret_ciphertext
    assert decrypt_credential(row) == ("cliente@example.it", "Segreto Molto Forte")
    assert mask_username("cliente@example.it").endswith("@example.it")
    row.portal = "cgn"
    with pytest.raises(InvalidTag):
        decrypt_credential(row)
