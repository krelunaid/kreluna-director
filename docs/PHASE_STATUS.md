# PHASE_STATUS

Legenda: PASS = implementato e testato. SANDBOX = adapter locale, non software fiscale vero. NOT-CERTIFIED = documenti e controlli pronti, non certificazione ISO.

| Fase | Modulo | Stato | Nota |
|---|---|---|---|
| 0 | Freeze architettura | PASS | docs + policy YAML |
| 1 | Scheletro Director + Agent | PASS | health + identity |
| 2 | Enrollment | PASS | token casuale, digest, 20 minuti, ruolo/tenant, revoca titolare |
| 3 | WSS + heartbeat + kill | PASS | challenge Ed25519, hub tenant, cancellazione cooperativa |
| 4 | Notepad | PASS | Windows o virtuale |
| 5 | Screenshot / evidenze | PASS | hash, cifratura, tenant |
| 6 | Task queue + routing | PASS | persistenza, idempotenza |
| 7 | Dashboard | PASS | chat, PC, prove |
| 8 | Planner IA | PASS | JSON/schema + policy |
| 9 | Approval Gateway | PARZIALE | uso singolo presente; payload/hash congelato e four-eyes mancanti |
| 10 | Automation toolkit | PASS | API→UI→Playwright→mouse in bounds, failsafe |
| 11 | Vision loop | PASS | max_steps, BLOCKED su dialoghi, no 30 FPS |
| 12 | Demo fattura e2e | PASS | BOZZA → approve → EMESSA demo |
| 13 | Multi-tenant + RBAC | PARZIALE | scope REST/WS presente; un viewer può ancora annullare task |
| 14 | Billing / licensing | PASS | webhook firmati, ACTIVE/GRACE/SUSPENDED (no Stripe live) |
| 15 | Hardening grant | PASS | Ed25519, nonce, device-bound |
| 16 | Audit / retention | PARZIALE | redaction e retention; nessuna protezione DB append-only/catena hash |
| 17 | Adapter gestionale | SANDBOX | Fatture sandbox locale, mai Agenzia reale |
| 18 | Production readiness | NOT-CERTIFIED | zip Mac/Windows con Python dentro; no firma codice / pentest |

Fuori perimetro voluto: invio F24/PEC/pagamenti reali, login automatico SPID/CNS,
mouse libero del modello e schermate inviate al modello.

La dicitura PASS riguarda il perimetro dimostrativo testato, non certificazione o uso
fiscale reale. Restano aperti i P0/P1 elencati in `docs/DIRECTOR-AUDIT.md`, in
particolare frozen payload/approvazione, endpoint demo, filtro segreti chat e firma
vendor degli aggiornamenti.

Versione 0.5.0 — programma installabile: Python è già dentro, lo studio non lo installa.
