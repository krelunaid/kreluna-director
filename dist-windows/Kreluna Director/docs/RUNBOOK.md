# Runbook locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp -n .env.example .env
make test
make demo
```

Dashboard: http://127.0.0.1:5173  
API: http://127.0.0.1:8080/health  
Login demo: `andrea@studio.demo` / `demo`

## Kill switch

Dalla dashboard: **Ferma tutto** → conferma. Oppure in chat: `Ferma tutto`.

## Licenza sospesa (simulazione)

In SQLite: `UPDATE licenses SET state='suspended' WHERE tenant_id='11111111-1111-1111-1111-111111111111';`

Il Director smette di accettare task operativi. Windows e i file del cliente restano intatti.

## Reset demo

```bash
rm -rf data/kreluna.db data/agent data/evidence
```
