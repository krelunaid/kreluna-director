from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.exceptions import InvalidTag
from kreluna_shared.crypto import decrypt_secret_text, encrypt_secret_text

from app.config import settings
from app.models import ClientCredential

MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 500
FORBIDDEN_LOGIN_KINDS = (
    "spid",
    "cns",
    "cie",
    "carta-identita-elettronica",
    "smart-card",
    "smartcard",
    "one-time-password",
    "otp",
)
SECRET_KINDS = {"password", "api_token", "client_secret"}
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
    "portal_url": {"link", "url", "link_portale", "portal_url", "indirizzo", "sito"},
    "portal_account": {"codice_studio", "studio", "account_portale", "portal_account"},
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
    portal_url: str
    portal_account: str
    username: str
    secret: str
    secret_kind: str
    credential_label: str

    def public(self) -> dict[str, str | int]:
        return {
            "row_number": self.row_number,
            "client_name": self.client_name,
            "portal": self.portal,
            "portal_url": self.portal_url,
            "portal_account_saved": bool(self.portal_account),
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


def normalize_portal_url(value: str) -> str:
    """Accept only browser addresses that cannot embed login credentials."""

    clean = value.strip()
    if not clean:
        return ""
    if len(clean) > 1000 or any(char in clean for char in ("\x00", "\r", "\n")):
        raise VaultImportError("link del portale non valido")
    parsed = urlparse(clean)
    if (
        parsed.scheme.lower() not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise VaultImportError("il link deve iniziare con https:// e non contenere credenziali")
    if parsed.scheme.lower() == "http" and parsed.hostname.lower() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise VaultImportError("per proteggere le credenziali il link del portale deve usare HTTPS")
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


def normalize_credential(
    *,
    client_name: str,
    portal: str,
    portal_url: str = "",
    portal_account: str = "",
    username: str,
    secret: str,
    secret_kind: str = "password",
    credential_label: str = "principale",
    row_number: int = 0,
) -> ParsedCredential:
    """Validate one credential from either the UI or a CSV row.

    Keeping one validation path prevents the manual form from bypassing the
    non-negotiable SPID/CNS/CIE/OTP exclusions enforced by CSV imports.
    """

    clean_client_name = _clean_public(client_name, field="cliente", max_length=200)
    client_key = client_key_for_name(clean_client_name)
    portal_raw = _clean_public(portal, field="portale", max_length=80)
    clean_portal = _ascii_slug(portal_raw, max_length=70)
    clean_portal = PORTAL_ALIASES.get(clean_portal, clean_portal)
    clean_portal_url = normalize_portal_url(portal_url)
    clean_portal_account = " ".join(portal_account.replace("\x00", "").split()).strip()
    if len(clean_portal_account) > 120:
        raise VaultImportError("codice studio/account portale troppo lungo")
    clean_username = _clean_public(username, field="username", max_length=320)
    clean_secret = secret.strip()
    if not clean_secret or len(clean_secret) > 2048 or "\x00" in clean_secret:
        raise VaultImportError("password/token mancante o troppo lungo")
    if clean_secret.casefold() in SECRET_PLACEHOLDERS:
        raise VaultImportError("sostituisci il valore di esempio con la password/token reale")
    clean_kind = secret_kind.strip().lower().replace("-", "_") or "password"
    clean_kind = {
        "token": "api_token",
        "api": "api_token",
        "clientsecret": "client_secret",
    }.get(clean_kind, clean_kind)
    if clean_kind not in SECRET_KINDS:
        raise VaultImportError("tipo di credenziale non supportato")
    clean_label = _clean_public(
        credential_label or "principale", field="etichetta", max_length=120
    )
    label_key = _ascii_slug(clean_label, max_length=100)
    if not client_key or not clean_portal or not label_key:
        raise VaultImportError("cliente, portale o etichetta non validi")
    forbidden_shape = f"{clean_portal}-{clean_kind}-{label_key}"
    if any(item in forbidden_shape for item in FORBIDDEN_LOGIN_KINDS):
        raise VaultImportError("SPID, CNS, CIE, smart card e OTP restano sempre manuali")
    return ParsedCredential(
        row_number=row_number,
        client_name=clean_client_name,
        client_key=client_key,
        portal=clean_portal,
        portal_url=clean_portal_url,
        portal_account=clean_portal_account,
        username=clean_username,
        secret=clean_secret,
        secret_kind=clean_kind,
        credential_label=label_key,
    )


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
            kind = _secret_kind(row, columns)
            label = str(row.get(columns.get("credential_label", "")) or "principale")
            item = normalize_credential(
                client_name=str(row.get(columns["client_name"]) or ""),
                portal=str(row.get(columns["portal"]) or ""),
                portal_url=str(row.get(columns.get("portal_url", "")) or ""),
                portal_account=str(row.get(columns.get("portal_account", "")) or ""),
                username=str(row.get(columns["username"]) or ""),
                secret=str(row.get(columns["secret"]) or ""),
                secret_kind=kind,
                credential_label=label,
                row_number=index,
            )
            dedupe = (item.client_key, item.portal, item.credential_label)
            if dedupe in seen:
                raise VaultImportError("accesso duplicato nello stesso CSV")
            seen.add(dedupe)
            parsed.append(item)
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


def tenant_vault_key(tenant_id: str) -> str:
    """Derive a distinct Fort Knox key for each studio from the server master key."""

    return hmac.new(
        settings.director_credential_key.encode("utf-8"),
        f"kreluna-fort-knox-v2:{tenant_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def encrypt_credential_fields(
    row: ClientCredential, *, username: str, secret: str, portal_account: str = ""
) -> None:
    row.username_ciphertext = encrypt_secret_text(
        tenant_vault_key(row.tenant_id),
        username,
        context=credential_context(row, "username"),
    )
    row.secret_ciphertext = encrypt_secret_text(
        tenant_vault_key(row.tenant_id),
        secret,
        context=credential_context(row, "secret"),
    )
    row.portal_account_ciphertext = (
        encrypt_secret_text(
            tenant_vault_key(row.tenant_id),
            portal_account,
            context=credential_context(row, "portal_account"),
        )
        if portal_account
        else ""
    )


def decrypt_username(row: ClientCredential) -> str:
    context = credential_context(row, "username")
    try:
        return decrypt_secret_text(
            tenant_vault_key(row.tenant_id), row.username_ciphertext, context=context
        )
    except InvalidTag:
        # Read credentials created before Fort Knox v2. They are rewritten with
        # the tenant-derived key the next time the owner updates them.
        return decrypt_secret_text(
            settings.director_credential_key, row.username_ciphertext, context=context
        )


def decrypt_credential(row: ClientCredential) -> tuple[str, str]:
    username = decrypt_username(row)
    context = credential_context(row, "secret")
    try:
        secret = decrypt_secret_text(
            tenant_vault_key(row.tenant_id), row.secret_ciphertext, context=context
        )
    except InvalidTag:
        secret = decrypt_secret_text(
            settings.director_credential_key, row.secret_ciphertext, context=context
        )
    return username, secret


def decrypt_portal_account(row: ClientCredential) -> str:
    if not row.portal_account_ciphertext:
        return ""
    context = credential_context(row, "portal_account")
    try:
        return decrypt_secret_text(
            tenant_vault_key(row.tenant_id), row.portal_account_ciphertext, context=context
        )
    except InvalidTag:
        return decrypt_secret_text(
            settings.director_credential_key,
            row.portal_account_ciphertext,
            context=context,
        )


def mask_username(value: str) -> str:
    if "@" in value:
        local, domain = value.split("@", 1)
        visible = local[:2]
        return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"
    if len(value) <= 2:
        return "•••"
    return value[:2] + "•" * max(3, len(value) - 3) + value[-1:]
