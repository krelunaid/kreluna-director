from __future__ import annotations

import pytest
from app.config import settings
from app.models import ClientCredential
from app.services.vault import (
    VaultImportError,
    credential_context,
    decrypt_credential,
    encrypt_credential_fields,
    mask_username,
    normalize_credential,
    parse_credentials_csv,
    tenant_vault_key,
)
from cryptography.exceptions import InvalidTag
from kreluna_shared.crypto import encrypt_secret_text


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


@pytest.mark.parametrize("portal", ["SPID", "cns", "CIE", "smart-card", "otp"])
def test_manual_credentials_refuse_personal_identity_and_otp(portal: str) -> None:
    with pytest.raises(VaultImportError, match="restano sempre manuali"):
        normalize_credential(
            client_name="Cliente Rossi",
            portal=portal,
            username="mario",
            secret="Segreto-123",
        )


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


def test_fort_knox_uses_distinct_tenant_keys_and_reads_legacy_rows() -> None:
    assert tenant_vault_key("tenant-a") != tenant_vault_key("tenant-b")
    legacy = ClientCredential(
        tenant_id="tenant-legacy",
        client_name="Cliente storico",
        client_key="cliente-storico",
        portal="webdesk",
        credential_label="principale",
        secret_kind="password",
        username_ciphertext="",
        secret_ciphertext="",
        updated_by="owner",
    )
    legacy.username_ciphertext = encrypt_secret_text(
        settings.director_credential_key,
        "legacy@example.it",
        context=credential_context(legacy, "username"),
    )
    legacy.secret_ciphertext = encrypt_secret_text(
        settings.director_credential_key,
        "Vecchio-Segreto",
        context=credential_context(legacy, "secret"),
    )
    assert decrypt_credential(legacy) == ("legacy@example.it", "Vecchio-Segreto")
