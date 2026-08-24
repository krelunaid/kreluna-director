# Cosa è meglio rispetto al PDF

Il piano originale è un ottimo vincolo di sicurezza. Questa codebase lo rende un prodotto usabile.

| Area | Piano originale | Qui |
|---|---|---|
| Avvio | 18 fasi, prima demo alla fase 5 | `make demo`: chat → agent → evidenza in un processo |
| Planner | Solo LLM → JSON | Planner italiano deterministico + LLM opzionale, policy ultima parola |
| Agent | Solo Windows | Windows + Linux/CI con gli stessi contratti |
| Gestionale | Rimandato alla fase 12/17 | Gestionale DEMO interno, mai portali reali |
| Contratti | Frammenti da copiare "nella fase corretta" | Pacchetto `kreluna_shared` importabile e testato |
| Dashboard | Wireframe testuale | Chat-first, italiano, live-ish via polling/WS eventi |
| Licenza | Stripe alla fase 14 | Stati licenza già autoritativi nel cloud (Stripe è adapter futuro) |
| Test | Criteri di uscita per fase | Suite pytest su policy, planner, enrollment, tenant, grant, invoice |

## Cosa resta volutamente fuori

- Invio F24 / PEC / pagamenti reali
- Mouse/visione come strategia principale
- Stripe live
- Installer firmato / auto-update
- Adapter TeamSystem o altri gestionali reali
