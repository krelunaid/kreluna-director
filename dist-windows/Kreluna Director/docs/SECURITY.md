# Sicurezza — regole non negoziabili

1. Niente shell remota arbitraria esposta al Director.
2. Niente `eval` / `exec` di codice prodotto dal modello.
3. Niente credenziali fiscali, bancarie o password nei prompt o nei log.
4. Niente operazioni irreversibili senza policy e, se richiesto, approvazione umana separata.
5. Niente licenza permanente controllata solo dal PC locale.
6. Niente backdoor per bloccare Windows, cancellare documenti del cliente o accedervi per motivi di pagamento.
7. Niente accesso trasversale tra studi.
8. Il kill switch deve funzionare anche se un task è in corso.
9. Ogni task è idempotente o protetto da doppia esecuzione.
10. Ogni risultato importante ha evidenza: dati riletti, screenshot, file, API response o hash.

## Dispatch Agent

```
handler = CAPABILITY_ALLOWLIST.get(task.capability)
if handler is None:
    raise PermissionError("CAPABILITY_NOT_ALLOWED")
```

Mai un dispatch dinamico da stringa arbitraria.

## Evidence

- Cattura solo dopo evento rilevante o su richiesta. Non stream continuo verso il modello.
- Cifrate a riposo, legate a `tenant_id`, `task_id`, `device_id`, timestamp, SHA-256.
- Retention configurabile; cancellazione registrata in audit.

## Approval token

Monouso, breve, legato a `approval_id + task_id + device_id + action + nonce`. Ricaricare la pagina non duplica l'azione.
