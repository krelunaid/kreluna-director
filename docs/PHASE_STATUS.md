# PHASE_STATUS

Legenda: PASS = implementato e coperto da test o demo eseguibile. DESIGN = contratto e policy presenti, senza integrazione esterna. SKIP = volutamente non in questo prototipo.

| Fase | Modulo | Stato | Nota |
|---|---|---|---|
| 0 | Freeze architettura | PASS | docs + policy YAML + parser |
| 1 | Scheletro Director + Agent | PASS | health + identity |
| 2 | Enrollment | PASS | codice monouso, revoca, no private key upload |
| 3 | WSS + heartbeat + kill | PASS | registry in-process, kill globale |
| 4 | Notepad | PASS | Windows pywinauto se c'è, altrimenti notepad virtuale |
| 5 | Screenshot / evidenze | PASS | PNG, hash, cifratura, tenant scope |
| 6 | Task queue + routing | PASS | SQLite persistente, idempotenza, lock GUI agent |
| 7 | Dashboard | PASS | chat, PC, task, evidenze, FERMA TUTTO |
| 8 | Planner IA | PASS | deterministico + schema + policy |
| 9 | Approval Gateway | PASS | preview, token monouso, approve/reject |
| 10 | Automation toolkit | DESIGN | API demo + allowlist; no mouse libero |
| 11 | Vision loop | DESIGN | contratto pronto, non stream FPS |
| 12 | Demo fattura e2e | PASS | BOZZA → approve → EMESSA demo |
| 13 | Multi-tenant + RBAC | PASS | scope server-side + ruoli |
| 14 | Billing Stripe | DESIGN | stati licenza cloud, no Stripe live |
| 15 | Hardening grant | PASS | HMAC grant, nonce, device-bound |
| 16 | Audit / retention | PASS | append-only, redaction, retention job |
| 17 | Adapter reale | SKIP | solo gestionale demo |
| 18 | Production readiness | SKIP | non candidato produzione fiscale |

Ultimo aggiornamento: prototipo migliorato 0.2.0.
