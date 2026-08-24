# PHASE_STATUS

Legenda: PASS = implementato e testato. SANDBOX = adapter locale, non software fiscale vero. NOT-CERTIFIED = documenti e controlli pronti, non certificazione ISO.

| Fase | Modulo | Stato | Nota |
|---|---|---|---|
| 0 | Freeze architettura | PASS | docs + policy YAML |
| 1 | Scheletro Director + Agent | PASS | health + identity |
| 2 | Enrollment | PASS | monouso, revoca |
| 3 | WSS + heartbeat + kill | PASS | registry, FERMA TUTTO |
| 4 | Notepad | PASS | Windows o virtuale |
| 5 | Screenshot / evidenze | PASS | hash, cifratura, tenant |
| 6 | Task queue + routing | PASS | persistenza, idempotenza |
| 7 | Dashboard | PASS | chat, PC, prove |
| 8 | Planner IA | PASS | JSON/schema + policy |
| 9 | Approval Gateway | PASS | token monouso |
| 10 | Automation toolkit | PASS | API→UI→Playwright→mouse in bounds, failsafe |
| 11 | Vision loop | PASS | max_steps, BLOCKED su dialoghi, no 30 FPS |
| 12 | Demo fattura e2e | PASS | BOZZA → approve → EMESSA demo |
| 13 | Multi-tenant + RBAC | PASS | viewer non chatta; scope tenant |
| 14 | Billing / licensing | PASS | webhook firmati, ACTIVE/GRACE/SUSPENDED (no Stripe live) |
| 15 | Hardening grant | PASS | Ed25519, nonce, device-bound |
| 16 | Audit / retention | PASS | append-only, redaction, retention |
| 17 | Adapter gestionale | SANDBOX | Fatture sandbox locale, mai Agenzia reale |
| 18 | Production readiness | NOT-CERTIFIED | zip Mac/Windows con Python dentro; no firma codice / pentest |

Fuori perimetro voluto: invio F24/PEC/pagamenti reali, portali Agenzia, mouse libero del modello.

Versione 0.5.0 — programma installabile: Python è già dentro, lo studio non lo installa.
