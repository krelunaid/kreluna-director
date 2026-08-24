# Production readiness (PDF fase 18)

Questo prototipo **non è certificato** ISO e **non è candidato** all’uso fiscale reale.

## Avvio fail-closed

Con `DIRECTOR_ENV=production` l'applicazione non parte finché non sono configurati
quattro segreti distinti di almeno 32 caratteri (`DIRECTOR_SIGNING_SEED`,
`DIRECTOR_SESSION_SECRET`, `DIRECTOR_EVIDENCE_KEY`, `KRELUNA_ENROLLMENT_CODE`) e le
credenziali iniziali del titolare (`DIRECTOR_BOOTSTRAP_EMAIL` e una
`DIRECTOR_BOOTSTRAP_PASSWORD` di almeno 14 caratteri). In produzione non vengono
creati account demo. Le password sono memorizzate con Argon2id; gli hash SHA-256
esistenti vengono migrati ad Argon2id al primo login valido.

Checklist coperta in codice/documenti:

- [x] Kill switch
- [x] Cross-tenant deny (test)
- [x] Grant firmati, nonce, device-bound
- [x] Approval token monouso
- [x] Audit + redaction
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
