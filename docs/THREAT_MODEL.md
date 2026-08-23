# Threat model — Kreluna Director

## Asset

- Token di sessione e grant operativi
- Chiavi dispositivo Agent
- Screenshot / evidenze (dati potenzialmente fiscali)
- Coda task e idempotency keys
- Stato licenza (autorità solo cloud)

## Minacce e controlli

| Minaccia | Scenario | Controllo |
|---|---|---|
| Furto token | Sessione dashboard copiata | Token firmati HMAC, scadenza breve, RBAC server-side |
| Agent modificato | Binario patchato per fingere `ACTIVE` | Grant firmati solo dal server; flag locale ignorato |
| Replay enrollment | Stesso `enrollment_code` riusato | Codice monouso, invalidato alla prima redeem |
| Replay grant | Token copiato e rimandato | Nonce persistito, `exp` breve, device binding |
| Cross-tenant | Query per `task_id` senza tenant | Ogni SELECT ha `tenant_id = current` |
| Screenshot leak | Evidence URL indovinabile | Path opaco, cifratura a riposo, check tenant+ruolo |
| Doppio task | Due fatture per lo stesso comando | `idempotency_key` univoca per tenant |
| PC offline | Agent esegue con grant vecchio | Grant a breve vita; offline ≠ licenza permanente |
| Prompt injection | Testo in una email/fattura che dice "ignora policy" | Policy engine dopo il planner; deny list; no shell |
| Kill ignorato | Task GUI continua dopo STOP | Flag locale `killed` + refuse handler + audit |
| License bypass | File `paid=true` sul PC | Nessuna decisione di licenza sul client |
| Credenziali in log | Password/IBAN nei prompt | Redaction automatica, divieto di mettere segreti nei prompt |
| Cross-device grant | Token di PC-01 usato su PC-02 | `device_id` nel grant verificato |
| Platform admin curiosity | Admin Kreluna legge fatture dello studio | Ruolo senza accesso evidenze fiscali di default |

## Fuori scope in questo prototipo

- Penetration test indipendente
- TPM/certificate store Windows (progettato, non obbligatorio in demo)
- Code signing MSIX
- Stripe live
