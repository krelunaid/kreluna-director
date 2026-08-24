# Manuale amministratore Kreluna

- Tenant isolati: ogni query ha `tenant_id`.
- Ruoli: platform_admin, studio_owner, approver, operator, viewer.
- Viewer: sola lettura. Non può chattare.
- Kill switch: titolare/approvatore, con conferma in dashboard.
- Licenza: ACTIVE / GRACE / SUSPENDED dal cloud. Pagamento fallito → GRACE 7 giorni → SUSPENDED.
- Webhook billing: `POST /billing/webhook` con `X-Kreluna-Signature` HMAC-SHA256.
- Revoca device: il PC non ottiene più grant.
- Evidence: cifrate, tenant-scoped, retention 72h.
- Agent Windows: `scripts/windows/Install-KrelunaAgent.ps1`.
- Agent Mac: `docs/MAC.md`.
