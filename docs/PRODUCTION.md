# Production readiness (PDF fase 18)

Questo prototipo **non è certificato** ISO e **non è candidato** all’uso fiscale reale.

Checklist coperta in codice/documenti:

- [x] Kill switch
- [x] Cross-tenant deny (test)
- [x] Grant firmati, nonce, device-bound
- [x] Approval token monouso
- [x] Audit + redaction
- [x] Retention evidenze
- [x] Licenza cloud ACTIVE/GRACE/SUSPENDED
- [x] Installer Agent Windows (script)
- [x] App Mac e Windows (zip installabili)
- [x] `/health`, `/ready`, `/update/manifest`
- [ ] Code signing MSIX / notarize Apple
- [ ] Stripe live
- [ ] Adapter Fatture in Cloud / Agenzia **reali**
- [ ] Penetration test indipendente
- [ ] DPA / AI Act review legale

Sospensione licenza: niente nuovi task Kreluna. Non si spegne Windows, non si sequestrano i file del cliente.
