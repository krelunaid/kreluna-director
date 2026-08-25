from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass

from kreluna_shared.crypto import decrypt_secret_text, encrypt_secret_text

from app.config import settings
from app.models import ClientCredential

MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 500
FORBIDDEN_LOGIN_KINDS = ("spid", "cns", "cie", "smart-card", "smartcard")
SECRET_KINDS = {"password", "api_token", "client_secret", "pin"}
SECRET_PLACEHOLDERS = {
    "cambia-questa-password",
    "inserisci-password",
    "password",
    "sostituisci",
    "token",
}

HEADER_ALIASES = {
    "client_name": {"cliente", "client", "client_name", "ragione_sociale", "azienda", "ditta"},
    "portal": {"portale", "portal", "sistema", "servizio", "provider", "programma"},
    "username": {"username", "utente", "user", "email", "login", "utenza"},
    "secret": {"password", "secret", "segreto", "token", "api_key", "chiave", "pin"},
    "secret_kind": {"tipo", "tipo_segreto", "secret_kind", "tipo_chiave"},
    "credential_label": {"etichetta", "label", "profilo", "nome_accesso"},
}

PORTAL_ALIASES = {
    "agenzia-delle-entrate": "ade",
    "agenzia-entrate": "ade",
    "fatture-e-corrispettivi": "ade",
    "fatture-corrispettivi": "ade",
    "web-desk": "webdesk",
    "desktop-telematico": "telematico",
    "camera-commercio": "comunica",
}


class VaultImportError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCredential:
    row_number: int
    client_name: str
    client_key: str
    portal: str
    username: str
    secret: str
    secret_kind: str
    credential_label: str

    def public(self) -> dict[str, str | int]:
        return {
            "row_number": self.row_number,
            "client_name": self.client_name,
            "portal": self.portal,
            "username_masked": mask_username(self.username),
            "secret_kind": self.secret_kind,
            "credential_label": self.credential_label,
        }


def _ascii_slug(value: str, *, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")[:max_length]
    return slug


def client_key_for_name(value: str) -> str:
    return _ascii_slug(value, max_length=180)


def _header(value: str) -> str:
    return _ascii_slug(value, max_length=80).replace("-", "_")


def _clean_public(value: str, *, field: str, max_length: int) -> str:
    clean = " ".join(value.replace("\x00", "").split()).strip()
    if not clean:
        raise VaultImportError(f"{field} mancante")
    if len(clean) > max_length:
        raise VaultImportError(f"{field} troppo lungo")
    return clean


def _canonical_columns(fieldnames: list[str]) -> dict[str, str]:
    columns: dict[str, str] = {}
    for original in fieldnames:
        normalized = _header(original)
        for canonical, aliases in HEADER_ALIASES.items():
            if normalized in aliases and canonical not in columns:
                columns[canonical] = original
                break
    missing = [name for name in ("client_name", "portal", "username", "secret") if name not in columns]
    if missing:
        labels = {
            "client_name": "cliente",
            "portal": "portale",
            "username": "username",
            "secret": "password/token",
        }
        raise VaultImportError("Colonne mancanti: " + ", ".join(labels[item] for item in missing))
    return columns


def _secret_kind(row: dict[str, str], columns: dict[str, str]) -> str:
    explicit = row.get(columns.get("secret_kind", ""), "").strip().lower().replace("-", "_")
    if not explicit:
        source_header = _header(columns["secret"])
        explicit = "api_token" if source_header in {"token", "api_key", "chiave"} else "password"
    aliases = {"token": "api_token", "api": "api_token", "clientsecret": "client_secret"}
    value = aliases.get(explicit, explicit)
    if value not in SECRET_KINDS:
        raise VaultImportError("tipo di credenziale non supportato")
    return value


def parse_credentials_csv(data: bytes) -> tuple[list[ParsedCredential], list[dict[str, int | str]]]:
    if not data:
        raise VaultImportError("Il CSV è vuoto")
    if len(data) > MAX_CSV_BYTES:
        raise VaultImportError("Il CSV supera 1 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise VaultImportError("Salva il CSV in formato UTF-8 e riprova") from exc
    if "\x00" in text:
        raise VaultImportError("Il CSV contiene dati non validi")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        delimiter = ";" if text.count(";") > text.count(",") else ","
        dialect = type("VaultDialect", (csv.excel,), {"delimiter": delimiter})
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise VaultImportError("Il CSV non contiene intestazioni")
    columns = _canonical_columns([str(item or "") for item in reader.fieldnames])
    parsed: list[ParsedCredential] = []
    warnings: list[dict[str, int | str]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(reader, start=2):
        if index > MAX_CSV_ROWS + 1:
            raise VaultImportError(f"Il CSV supera {MAX_CSV_ROWS} righe")
        if not any(str(value or "").strip() for value in row.values()):
            continue
        try:
            client_name = _clean_public(
                str(row.get(columns["client_name"]) or ""), field="cliente", max_length=200
            )
            client_key = client_key_for_name(client_name)
            portal_raw = _clean_public(
                str(row.get(columns["portal"]) or ""), field="portale", max_length=80
            )
            portal = _ascii_slug(portal_raw, max_length=70)
            portal = PORTAL_ALIASES.get(portal, portal)
            username = _clean_public(
                str(row.get(columns["username"]) or ""), field="username", max_length=320
            )
            secret = str(row.get(columns["secret"]) or "").strip()
            if not secret or len(secret) > 2048 or "\x00" in secret:
                raise VaultImportError("password/token mancante o troppo lungo")
            if secret.casefold() in SECRET_PLACEHOLDERS:
                raise VaultImportError("sostituisci il valore di esempio con la password/token reale")
            kind = _secret_kind(row, columns)
            label = str(row.get(columns.get("credential_label", "")) or "principale")
            label = _clean_public(label, field="etichetta", max_length=120)
            label_key = _ascii_slug(label, max_length=100)
            if not client_key or not portal or not label_key:
                raise VaultImportError("cliente, portale o etichetta non validi")
            forbidden_shape = f"{portal}-{kind}-{label_key}"
            if any(item in forbidden_shape for item in FORBIDDEN_LOGIN_KINDS):
                raise VaultImportError("SPID, CNS, CIE e smart card restano sempre manuali")
            dedupe = (client_key, portal, label_key)
            if dedupe in seen:
                raise VaultImportError("accesso duplicato nello stesso CSV")
            seen.add(dedupe)
            parsed.append(
                ParsedCredential(
                    row_number=index,
                    client_name=client_name,
                    client_key=client_key,
                    portal=portal,
                    username=username,
                    secret=secret,
                    secret_kind=kind,
                    credential_label=label_key,
                )
            )
        except VaultImportError as exc:
            warnings.append({"row_number": index, "message": str(exc)})
    if not parsed:
        detail = str(warnings[0]["message"]) if warnings else "nessuna riga valida"
        raise VaultImportError("Nessun accesso importabile: " + detail)
    return parsed, warnings


def credential_context(row: ClientCredential, field: str) -> str:
    return (
        f"kreluna-vault-v1:{row.tenant_id}:{row.client_key}:"
        f"{row.portal}:{row.credential_label}:{field}"
    )


def encrypt_credential_fields(row: ClientCredential, *, username: str, secret: str) -> None:
    row.username_ciphertext = encrypt_secret_text(
        settings.director_credential_key,
        username,
        context=credential_context(row, "username"),
    )
    row.secret_ciphertext = encrypt_secret_text(
        settings.director_credential_key,
        secret,
        context=credential_context(row, "secret"),
    )


def decrypt_username(row: ClientCredential) -> str:
    return decrypt_secret_text(
        settings.director_credential_key,
        row.username_ciphertext,
        context=credential_context(row, "username"),
    )


def decrypt_credential(row: ClientCredential) -> tuple[str, str]:
    username = decrypt_username(row)
    secret = decrypt_secret_text(
        settings.director_credential_key,
        row.secret_ciphertext,
        context=credential_context(row, "secret"),
    )
    return username, secret


def mask_username(value: str) -> str:
    if "@" in value:
        local, domain = value.split("@", 1)
        visible = local[:2]
        return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"
    if len(value) <= 2:
        return "•••"
    return value[:2] + "•" * max(3, len(value) - 3) + value[-1:]
