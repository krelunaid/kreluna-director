# Production readiness (PDF fase 18)

Questo prototipo **non è certificato** ISO e **non è candidato** all’uso fiscale reale.

## Avvio fail-closed

Con `DIRECTOR_ENV=production` l'applicazione non parte finché non sono configurati
quattro segreti distinti di almeno 32 caratteri (`DIRECTOR_SIGNING_SEED`,
`DIRECTOR_SESSION_SECRET`, `DIRECTOR_EVIDENCE_KEY`, `DIRECTOR_CREDENTIAL_KEY`) e le
credenziali iniziali del titolare (`DIRECTOR_BOOTSTRAP_EMAIL` e una
`DIRECTOR_BOOTSTRAP_PASSWORD` di almeno 14 caratteri). In produzione non vengono
creati account demo. Le password sono memorizzate con Argon2id; gli hash SHA-256
esistenti vengono migrati ad Argon2id al primo login valido.

Anche la modalità desktop installata applica lo stesso fail-closed. Al primo avvio
genera quattro segreti distinti per installazione, con permessi locali `0600`, e
credenziali titolare casuali. I codici Agent non sono segreti globali di configurazione:
sono token casuali, monouso, validi 20 minuti, legati a tenant e ruolo e conservati
nel database soltanto come digest.

## Provider IA e diagnostica

Grok, Ollama e OpenAI hanno configurazioni separate per indirizzo, chiave e modello
(vedi `.env.example`). La scelta del titolare viene salvata per studio. La dashboard
esegue un health check con cache breve e distingue: provider non configurato,
autenticazione rifiutata, timeout, provider non disponibile e modello assente. Se il
planner IA fallisce, il Director non usa una risposta deterministica come se nulla fosse:
ferma la richiesta, mostra la causa e registra `planner.ai_error` nell'audit.

Gli errori task delle ultime 24 ore sono mostrati come attivi; quelli più vecchi restano
nello storico. Anche `tasks_today` usa la stessa finestra temporale invece di contare
tutti i task presenti nel database.

Checklist coperta in codice/documenti:

- [x] Kill switch tenant-scoped e cancellazione cooperativa tra i passi Agent
- [x] Cross-tenant deny (test)
- [x] Grant firmati, nonce, device-bound
- [x] WebSocket Agent challenge-response; dashboard autenticata e hub per tenant
- [x] Risultati e richieste HTTP Agent firmati per intero, legati all'endpoint e
      al PC assegnato, con timestamp e anti-replay
- [ ] Approval legata a payload congelato e hash immutabile
- [ ] Audit append-only protetto dal database
- [x] Retention evidenze
- [x] Licenza cloud ACTIVE/GRACE/SUSPENDED
- [x] Installer Agent Windows (script)
- [x] App Mac e Windows (zip installabili, Python incluso)
- [x] `/health`, `/ready`, `/update/manifest`
- [ ] Code signing MSIX / notarize Apple
- [ ] Stripe live
- [ ] Adapter Fatture in Cloud / Agenzia **reali**
- [ ] Penetration test indipendente
- [ ] DPA / AI Act review legale

Sospensione licenza: niente nuovi task Kreluna. Non si spegne Windows, non si sequestrano i file del cliente.
