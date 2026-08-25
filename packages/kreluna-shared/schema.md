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

`challenge`, `hello`, `heartbeat`, `task`, `kill`, `pause`, `resume`,
`cancel_task`, `task_result`, `killed`.

Il Director autentica `hello` con una challenge breve firmata dalla chiave Ed25519
del device. Il risultato HTTP contiene `device_id`, `task_id`, timestamp, nonce,
esito, dati ed evidenze sotto un'unica firma canonica; nonce e risultati tardivi
sono rifiutati. Anche Cassaforte e API fattura demo ricevono richieste firmate sul
corpo completo e sul percorso HTTP, con timestamp e nonce monouso.

I task operativi portano un grant Ed25519 firmato dal server: `tenant_id + device_id + task_id + capability + exp + nonce`.
