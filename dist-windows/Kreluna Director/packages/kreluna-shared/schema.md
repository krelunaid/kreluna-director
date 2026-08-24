# Contratti condivisi

Fonte di verità eseguibile: `kreluna_shared`.

## Capability allowlist

- `notepad_write` `{ text }`
- `invoice_prepare_demo` `{ client_name, description, net_eur, vat_rate }`
- `invoice_submit_demo` `{ draft_id }`
- `document_check` `{ scope }`
- `email_draft` `{ subject, body, to? }`

Tutto il resto è rifiutato. `eval`, shell remota e export credenziali sono deny fissi.

## Protocollo Agent

`hello`, `heartbeat`, `task`, `kill`, `pause`, `resume`, `task_result`, `killed`.

I task operativi portano un grant Ed25519 firmato dal server: `tenant_id + device_id + task_id + capability + exp + nonce`.
