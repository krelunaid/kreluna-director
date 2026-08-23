# Kreluna Director — Architettura

TU PARLI SOLO CON KRELUNA DIRECTOR. Il Director capisce l'obiettivo, sceglie gli agenti, manda task strutturati, raccoglie prove e chiede approvazione prima delle azioni sensibili.

## Migliorie rispetto al piano originale

Il PDF è la specifica di sicurezza. Questa implementazione la rispetta e la rafforza:

1. **Contratti eseguibili, non solo markdown.** I modelli Pydantic in `kreluna_shared` sono la fonte di verità. Capability sconosciuta = rifiuto.
2. **Planner deterministico + LLM opzionale.** L'intelligenza non dipende da una chiave API. Se c'è un LLM, il JSON viene comunque validato e la policy vince sempre sul modello.
3. **Agent cross-platform.** Stesso protocollo su Windows e Linux. Su Linux il "Blocco Note" è un notepad virtuale con evidenza PNG: la demo gira anche in CI e in cloud.
4. **Gestionale DEMO interno.** Nessun portale fiscale reale. La fattura vive in memoria/SQLite nello Director.
5. **SQLite di default.** Un comando avvia API + dashboard + agent, senza Postgres obbligatorio.
6. **Grant firmati e nonce** già nella prima versione operativa.
7. **Chat-first.** La dashboard è un centro di comando, non un elenco di form.
8. **Isolamento tenant in ogni query.** Nessuna lookup per solo `id`.

## Flusso

```
[ UTENTE / TITOLARE ]
        |
        v
[ KRELUNA DIRECTOR ]
 Planner IA  |  Policy Engine  |  Task Queue
 Approval    |  Agent Registry |  Audit / Evidence
 Tenant/RBAC |  Licensing      |  Demo Gestionale
        |
   WSS / TLS
        |
[ KRELUNA AGENT  PC-01 / PC-02 / PC-03 ]
 API ufficiale -> UI Automation -> Playwright -> visione/mouse (fallback, non in questo build)
        |
 screenshot / structured read / hash
        v
[ VERIFICA + APPROVAZIONE UMANA ]
```

## Confini

| Componente | Contiene | Non contiene |
|---|---|---|
| Director cloud | cervello, policy, coda, licenze, evidenze | mouse, password fiscali |
| Agent | allowlist di tool, lock GUI, kill switch | chiave privata server, licenza `paid=true` |
| Dashboard | chat, PC, task, prove, approve/rifiuta | dati di altri studi |

## Identità

- Ogni studio è un `tenant_id`.
- Ogni PC ha `agent_id` (stabile, configurato) e `device_id` (assegnato all'enrollment).
- L'Agent genera una coppia Ed25519 locale. La privata non lascia il PC.
- I task operativi richiedono un grant firmato dal server, breve, legato a tenant+device+task+capability+nonce.

## Classificazione rischio

`LOW` / `MEDIUM` / `HIGH` / `CRITICAL`. HIGH e CRITICAL passano dall'Approval Gateway. Il modello non può abbassare il rischio.

## Automazione

Ordine di preferenza, invariato e vincolante:

1. API ufficiale
2. Windows UI Automation
3. Playwright / DOM
4. Visione + mouse solo come fallback, mai coordinate libere del modello

Questo prototipo usa (1) per il gestionale demo e un tool allowlistato per il notepad. Nessuna shell remota, nessun `eval`/`exec` di output IA.

## Kill switch

Un kill globale arriva a tutti gli Agent connessi. L'Agent imposta `safety.killed = True`, cancella il task corrente e rifiuta nuovi task fino a `resume` autorizzato. Funziona anche a task in corso.

## Licenza

Stati: `ACTIVE`, `GRACE`, `RESTRICTED`, `SUSPENDED`, `TERMINATED`.

Sospensione = il cloud smette di emettere grant. Non si spegne Windows, non si cifrano/cancellano i documenti del cliente, non esiste backdoor di pagamento.
