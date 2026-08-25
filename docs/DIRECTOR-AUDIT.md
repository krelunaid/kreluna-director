# Kreluna Director — audit tecnico Fase 0

Data: 25 agosto 2026
Base verificata: `v0.5.15`, commit `f31068b` sul branch
`cursor/kreluna-director-381b`
Ambito: repository applicativo, pacchetti desktop, API, dashboard, Agent, database,
autenticazione, provider IA, policy, approvazioni, aggiornamenti, test e configurazione
GitHub del branch predefinito.

Questa fase è soltanto di audit. Non modifica il comportamento del programma, la
grafica, il database o le barriere di sicurezza esistenti.

## Verdetto esecutivo

Kreluna Director 0.5.15 è un prototipo locale dimostrativo con diversi controlli utili
già presenti, ma **non è pronto per dati o operazioni fiscali reali**. Non devono essere
abilitati invii F24, PEC, pagamenti, login automatici SPID/CNS/CIE, invii di fatture o
altre azioni irreversibili finché i P0 di questo documento non sono chiusi e collaudati.

Il problema principale non è il modello IA: Grok produce soltanto un piano strutturato.
Il rischio attuale è nel canale Director-Agent e nel ciclo approvazione-esecuzione. Un
Agent può collegarsi senza autenticare la WebSocket; alcuni codici di enrollment sono
prevedibili e riutilizzabili; il risultato firmato non è vincolato al corpo completo né
all'Agent assegnato; l'approvazione non congela e non firma i dati economici. Inoltre il
pacchetto desktop usa ancora segreti demo condivisi per sessioni, grant ed evidenze.

Il sistema può continuare a essere provato come demo locale, senza credenziali reali e
senza collegamenti operativi reali. La Cassaforte e l'automazione dei portali devono
restare disabilitate per clienti reali fino alla chiusura dei P0.

## Controlli già presenti e verificati

- Hash password Argon2id con sale casuale e migrazione degli hash precedenti.
- Configurazione production fail-closed quando `DIRECTOR_ENV=production` è davvero
  impostato.
- Provider IA separati Grok, Ollama e OpenAI, health check esplicito e nessun fallback
  IA silenzioso.
- Chiavi IA e credenziali clienti cifrate con AES-GCM e contesto tenant/provider.
- Planner IA con output JSON validato, allowlist di capability e policy applicata dopo
  il modello.
- Deny list esplicita per shell remota, `eval`, export credenziali e disattivazione della
  sicurezza.
- Nessuna capability di invio reale F24/PEC/pagamenti e nessun login automatico
  SPID/CNS/CIE.
- Le schermate sono salvate come evidenze cifrate; non vengono inserite nel prompt IA.
- Filtri `tenant_id` presenti nella maggior parte delle API REST lette dalla dashboard.
- Grant Ed25519 brevi, legati a task, device e capability, verificati dall'Agent.
- Chiavi private Ed25519 degli Agent salvate localmente con permesso `0600` dove
  supportato.
- CI con lint Python, 172 test e build TypeScript/Vite. Sul branch predefinito lo status
  `quality` è obbligatorio, aggiornato e applicato anche agli amministratori.
- Release Mac e Windows riproducibili dalla CI con checksum SHA-256.
- Finestra nativa Mac vincolata a `http://127.0.0.1:8080` e navigazione esterna aperta
  nel browser di sistema.

Questi controlli vanno conservati. Non compensano però i P0 sotto elencati.

## Stack e architettura reale

| Area | Implementazione attuale | Nota operativa |
| --- | --- | --- |
| Dashboard | React 18, TypeScript, Vite | Token di sessione in `localStorage` |
| API | FastAPI, Pydantic, SQLAlchemy async | Uvicorn locale nel pacchetto desktop |
| Database | SQLite + aiosqlite di default | `create_all`, nessun sistema di migrazioni |
| Director | Planner deterministico + LLM opzionale | Crea task; non chiama direttamente tool del PC |
| IA | API OpenAI-compatible per Grok/OpenAI/Ollama | Solo testo digitato dall'utente |
| Agent | Python asyncio, WebSocket, Ed25519 | Allowlist statica di handler |
| Mac | Swift/AppKit/WebKit + AppleScript/browser DOM | App solo Apple Silicon nel pacchetto attuale |
| Windows | Python incorporato + WebView2 | Automazione portali ancora più limitata del Mac |
| Evidenze | PNG cifrati AES-GCM su filesystem + metadati SQLite | Screenshot dell'intero schermo, non mascherati |
| Aggiornamenti | GitHub Releases + ZIP + SHA-256 | Mac automatico; firma ad-hoc, non notarizzata |
| CI/CD | GitHub Actions | CI obbligatoria sul branch; release su tag |

### Flusso effettivo

1. La dashboard invia il testo a `POST /chat`.
2. Il planner deterministico prova a riconoscerlo; soltanto i messaggi sconosciuti
   passano al provider IA configurato.
3. `apply_policy` valida argomenti, capability, licenza, rischio e necessità di
   approvazione.
4. Il Director salva un `Task` e, se non richiede approvazione, lo mette in coda.
5. Il dispatcher sceglie un Agent e gli invia task, argomenti e grant firmato via
   WebSocket.
6. L'Agent verifica il grant e chiama un handler preso da una allowlist statica.
7. L'Agent invia risultato ed eventuali evidenze a `POST /agent/ingest`.
8. Solo la fattura demo crea oggi una riga `Approval`; l'approvazione crea un nuovo task
   `invoice_submit_demo`.

Manca un'entità `Operation` che rappresenti l'intero ciclo controllato richiesto:
PREPARE → CONTROL → FREEZE → DISPLAY → HUMAN APPROVAL → VERIFY → EXECUTE → RECEIPT →
AUDIT.

## Database e modello di stato

Tabelle presenti:

- `tenants`, `users`, `licenses`;
- `devices`, `enrollment_codes`, `agent_slots`;
- `tasks`, `approvals`, `used_nonces`;
- `evidence`, `audit_events`;
- `invoice_drafts`;
- `ai_selections`, `ai_provider_credentials`;
- `client_credentials`.

Assenze bloccanti:

- nessuna tabella `operations` o equivalente;
- nessun `operation_type`, `payload_version`, `payload_hash` o `frozen_payload`;
- nessuna versione ottimistica della riga e nessuna macchina a stati centralizzata;
- nessun legame immutabile tra approvazione e contenuto economico;
- nessuna tabella di esecuzione con stato `never_attempted`, `started`, `confirmed` o
  `uncertain`;
- nessuna ricevuta normalizzata con hash, stato remoto, timestamp e identificativo
  esterno;
- nessuna seconda approvazione o separazione preparatore/approvatore;
- nessuna migrazione versionata del database;
- nessuna catena hash o protezione append-only per l'audit.

Gli stati attuali dei task sono `queued`, `assigned`, `running`, `waiting_approval`,
`completed`, `failed`, `cancelled`, `blocked`. Non coincidono con gli stati operativi
richiesti e vengono modificati direttamente in più router e servizi, senza una funzione
unica che validi le transizioni.

## Autenticazione e autorizzazione

### Utenti dashboard

- Sessione bearer firmata HMAC-SHA256, scadenza predefinita 12 ore.
- Il ruolo e il tenant vengono riletti dal database a ogni richiesta autenticata.
- Ruoli dichiarati: `platform_admin`, `studio_owner`, `approver`, `operator`, `viewer`.
- Non ci sono MFA, revoca sessione, rotazione token, rate limit o blocco tentativi login.
- Il token è conservato in `localStorage`, quindi un futuro XSS avrebbe accesso alla
  sessione.
- L'email non è univoca nel database e il login cerca globalmente per email: la stessa
  email su due tenant può causare errore o ambiguità.

### Agent

- L'enrollment iniziale riceve una chiave pubblica Ed25519.
- I grant operativi sono firmati dal Director e verificati dall'Agent.
- Le chiamate risultato e Cassaforte sono firmate dall'Agent, ma la firma copre soltanto
  il `task_id`, non metodo, capability, esito, dati, hash del payload o nonce.
- La WebSocket Agent non usa firma, challenge, certificato o token di device.

### RBAC critico

Il ruolo `studio_owner` può preparare dalla chat e approvare lo stesso lavoro. Non è
applicato il principio dei quattro occhi. L'endpoint di annullamento task è disponibile
anche a `viewer`, perché richiede soltanto `get_actor`. Anche alcuni endpoint demo non
impongono un ruolo operativo.

## Dove l'IA può influenzare o causare azioni

### Percorso IA

`packages/kreluna-shared/src/kreluna_shared/llm.py` invia al provider soltanto:

- un system prompt statico;
- il testo digitato dall'utente, fino a 4.000 caratteri.

Il modello può proporre solo capability in `PLANNABLE`. Il risultato è trasformato in
`PlannedTask`, poi passa da `validate_capability_args` e `PolicyEngine`. Il rischio
proposto dal modello non è considerato autoritativo. Non esiste una chiamata diretta del
modello a shell, browser, file o mouse.

### Percorso di esecuzione

L'IA influenza comunque il sistema creando un task. Il task attraversa:

`POST /chat` → `enqueue_planned` → `dispatch_queued` → WebSocket Agent →
`CAPABILITY_ALLOWLIST`.

Le capability attualmente eseguibili sono preparazione demo, controlli in lettura,
apertura/lettura/compilazione limitata di portali, Blocco Note e bozze. La capability
`portal_open` può aprire un sito reale e, se richiesto, compilare username e password
dalla Cassaforte, fermandosi prima del login/invio.

### Confine prompt non ancora completo

Le schermate non vengono inviate al modello. Tuttavia il testo chat viene inoltrato
senza un filtro DLP: se un utente incolla una password, token, IBAN o altro segreto nel
messaggio, quel testo può raggiungere Grok/OpenAI/Ollama. La sola redazione dell'audit
non protegge la richiesta in uscita. Va aggiunto un rifiuto o una redazione prima del
provider.

## P0 — blocchi immediati prima di qualsiasi uso reale

### P0-01 — il pacchetto desktop usa segreti demo condivisi

Evidenza:

- `apps/director-api/app/config.py:37-55` contiene valori di sviluppo statici per
  signing seed, session secret, evidence key ed enrollment code;
- `apps/director-desktop/kreluna_desktop.py:55-64` genera per installazione soltanto la
  chiave della Cassaforte;
- `packaging/macos/Kreluna:33-43` e `packaging/windows/Avvia.bat:24-31` non impostano
  `DIRECTOR_ENV=production` né segreti casuali per sessioni, grant ed evidenze;
- `apps/director-api/app/seed.py:50-82` crea gli account demo con password `demo`.

Impatto: le installazioni desktop hanno la stessa chiave di firma sessione, la stessa
chiave di grant, la stessa chiave evidenze e credenziali demo note. L'ascolto su
`127.0.0.1` riduce l'esposizione di rete, ma non protegge da processi locali, estensioni
o pagine ostili capaci di raggiungere localhost, né da una futura esposizione remota.

Correzione immediata: modalità desktop esplicita con segreti unici generati alla prima
esecuzione, permessi stretti, bootstrap titolare obbligatorio e rimozione delle
credenziali demo dal pacchetto vendibile.

### P0-02 — enrollment prevedibile, riutilizzabile e capace di sostituire la chiave

Evidenza:

- `apps/director-api/app/seed.py:130-145` genera codici come
  `KRELUNA-PC-FATTURE`;
- `apps/director-api/app/routers/core.py:330-379` permette la reinstallazione dello
  slot e sovrascrive `device.public_key` senza provare il possesso della vecchia chiave;
- `tests/integration/test_director.py:265-306` codifica questo comportamento come test
  atteso.

Impatto: chi conosce il codice prevedibile può prendere l'identità dello slot, ruotare
la chiave del device e rendere non attendibili task, firme e Cassaforte.

Correzione immediata: codici casuali ad alta entropia, monouso e con scadenza; una
reinstallazione deve essere autorizzata dal titolare o firmata con la vecchia chiave;
rotazione e revoca devono produrre audit esplicito.

### P0-03 — WebSocket Agent e dashboard senza autenticazione

Evidenza:

- `apps/director-api/app/routers/ws.py:58-90` accetta `device_id` dichiarato dal client
  senza challenge o firma;
- `apps/director-api/app/routers/ws.py:132-142` registra dashboard non autenticate;
- `apps/director-api/app/services/registry.py:15-52` conserva connessioni globali non
  separate per tenant.

Impatto: conoscendo un UUID, un client può presentarsi come Agent, ricevere task e grant,
alterare presenza/capability dichiarate o causare denial of service. Una dashboard non
autenticata può ricevere eventi globali.

Correzione immediata: handshake challenge-response Ed25519, binding a tenant/device,
WSS obbligatorio fuori localhost, scadenza della challenge e hub partizionato per
tenant. La dashboard WebSocket deve verificare la sessione e iscriversi a un solo
tenant.

### P0-04 — un Agent può alterare task non assegnati e il risultato non è firmato

Evidenza:

- `apps/director-api/app/routers/agent_io.py:168-180` verifica la firma del solo
  `task_id`, ma non verifica `task.assigned_device_id`, stato atteso o capability;
- `apps/director-api/app/routers/agent_io.py:207-219` accetta esito e `result` dichiarati
  dal device;
- la firma non copre `ok`, `result`, `error`, evidenze o un nonce.

Impatto: un Agent regolarmente iscritto nello stesso studio può completare, fallire o
inquinare un task assegnato a un altro PC. Un replay dello stesso corpo non è respinto.

Correzione immediata: firma canonica dell'intera richiesta con timestamp e nonce;
verifica di tenant, device assegnato, capability, stato e grant; consumo atomico del
nonce; limiti su numero/dimensione evidenze; rifiuto di risultati tardivi o duplicati.

### P0-05 — l'approvazione non congela il contenuto e accetta la verifica dell'Agent

Evidenza:

- `apps/director-api/app/routers/agent_io.py:224-250` usa
  `body.result.verification` se presente e lo ricalcola soltanto se manca;
- la preview è JSON modificabile e non ha `payload_hash`, versione o firma;
- `apps/director-api/app/routers/work.py:289-353` approva usando soltanto `draft_id` e
  non confronta i dati mostrati con `Task.args_json` e `InvoiceDraft`;
- `Approval.token_nonce` non è presentato o verificato dal client; il controllo reale è
  un booleano `token_used`.

Impatto: la manomissione richiesta dalla specifica, per esempio da 1.000 euro a 10.000
euro, non ha una garanzia crittografica che la blocchi. Un Agent compromesso può
dichiarare `verification.ok=true`, proporre un'altra bozza e ottenere una preview
apparentemente valida.

Correzione immediata: ricalcolo server-side obbligatorio; payload canonico versione 1;
SHA-256 persistito; snapshot immutabile; confronto del hash prima di approvazione e
prima di esecuzione; qualunque modifica invalida tutte le approvazioni.

### P0-06 — kill switch globale e non realmente interrompente

Evidenza:

- `apps/director-api/app/services/orchestrator.py:178-210` filtra il database per
  tenant, ma poi chiama `hub.broadcast_agents`, che invia `kill` a tutti gli Agent di
  tutti i tenant;
- `apps/kreluna-agent/agent/main.py:117-163` imposta il flag su `kill`, ma un handler già
  in esecuzione, specialmente dentro `asyncio.to_thread`, non viene cancellato;
- `SafetyState.assert_not_killed` è controllato soltanto prima di avviare l'handler.

Impatto: il titolare di uno studio può fermare Agent appartenenti ad altri studi. Un
task GUI già partito può continuare dopo “FERMA TUTTO”, contrariamente alla
documentazione attuale.

Correzione immediata: broadcast limitato ai device del tenant; token di cancellazione
cooperativa verificato a ogni passo; timeout e terminazione controllata; stato
`BLOCKED/CANCELLED` attestato dall'Agent; test con task in corso.

### P0-07 — endpoint demo e simulazione licenza aggirano i gateway dichiarati

Evidenza:

- `apps/director-api/app/routers/work.py:525-560` permette a qualsiasi utente
  autenticato, incluso `viewer`, di creare ed emettere direttamente fatture demo;
- `apps/director-api/app/routers/agent_io.py:268-309` permette a un device firmante di
  preparare o emettere una bozza demo senza provare task, grant e approvazione;
- `apps/director-api/app/routers/billing.py:88-101` consente al titolare di impostare la
  propria licenza su `active` anche fuori da una modalità test esplicita.

Impatto: oggi le azioni sono demo, quindi non inviano nulla all'esterno. La struttura è
però un bypass pericoloso: collegare in futuro un adapter reale a questi endpoint
eluderebbe approvazione e autorità cloud della licenza.

Correzione immediata: endpoint demo compilati solo in test o protetti da feature flag
`false` per default; mai riuso per adapter reali; simulazione licenza disponibile solo
in ambiente test; tutte le mutazioni passano dall'operation engine.

### P0-08 — aggiornamento automatico non autenticato da un'identità Kreluna

Evidenza:

- `scripts/macos/build-mac-app.sh:66-69` applica firma ad-hoc (`--sign -`), non firma
  Developer ID e notarizzazione;
- `packages/kreluna-shared/src/kreluna_shared/macos_update.py:235-271` scarica ZIP e
  checksum dalla stessa GitHub Release;
- `validate_bundle` verifica che una firma sia internamente valida, ma non controlla
  Team ID/certificato Kreluna;
- durante l'installazione viene rimosso l'attributo di quarantena.

Impatto: la sola compromissione del canale GitHub Release può fornire sia un pacchetto
malevolo sia il suo checksum. La firma ad-hoc non prova chi lo ha pubblicato.

Correzione immediata: firma Developer ID / Authenticode, notarizzazione Apple, identità
del firmatario fissata nel client, manifest firmato offline con chiave di release
separata e rotazione documentata. Non rimuovere la quarantena a un artefatto privo di
identità verificata.

### P0-09 — segreti digitati in chat possono uscire verso il provider IA

Evidenza: `packages/kreluna-shared/src/kreluna_shared/llm.py:248-275` invia
`message[:4000]` al provider senza classificazione o redazione preventiva.

Impatto: l'architettura impedisce alla Cassaforte di entrare nel prompt, ma non impedisce
all'utente di incollare per errore una password, token o credenziale nel testo.

Correzione immediata: classificatore locale deterministico, rifiuto esplicito dei
segreti, redazione prima della rete e test che ispeziona il corpo HTTP inviato al
provider.

## P1 — hardening funzionale necessario

| ID | Lacuna reale | Intervento richiesto |
| --- | --- | --- |
| P1-01 | Nessun aggregate `Operation` e nessuna macchina a stati | Modello unico con stati richiesti, transizioni centralizzate e versione ottimistica |
| P1-02 | Nessun frozen payload/hash/versione | JSON canonico, SHA-256, snapshot immutabile e invalidazione approvazioni |
| P1-03 | Nessun four-eyes/dual approval | Separare preparatore, approvatore ed esecutore; due approvazioni sopra soglia |
| P1-04 | Race su approvazione e enqueue | Transazione atomica, compare-and-swap/lock, vincoli unici e risposta idempotente |
| P1-05 | Idempotenza limitata ai task vivi | Chiave per operazione ed esecuzione; completed non rieseguibile senza nuova operazione |
| P1-06 | Nessun receipt normalizzato | Ricevuta con hash, stato remoto, ID esterno, timestamp, esito e stato incerto |
| P1-07 | Audit incompleto e modificabile | Eventi per ogni transizione; append-only applicativo e DB; correlazione operation/task/execution |
| P1-08 | Nessuna migrazione DB | Alembic o equivalente, schema versionato, upgrade/rollback e backup testato |
| P1-09 | Rate limit assente | Login, chat, enrollment, WebSocket, health IA, import CSV, approvazioni e Agent I/O |
| P1-10 | Sessioni senza revoca/MFA | Session ID server-side, logout/revoca, rotazione, MFA per approvatori critici |
| P1-11 | Screenshot intero non mascherato | Cattura della sola finestra/area consentita, mascheramento e conferma prima dell'evidenza |
| P1-12 | `demo_only` è solo metadato | Enforcement server-side per ambiente e adapter; UI “DEMO” non ambigua |
| P1-13 | Portal config incompleta | URL/selector versionati, dominio esatto, allowlist redirect e test per portale |
| P1-14 | SQLite e `create_all` non bastano per concorrenza | Database supportato in produzione, transazioni/lock, pool e test multi-worker |
| P1-15 | Kill/feature flag non persistenti per integrazione | Kill switch globale e per feature, default `false`, audit e autorizzazione forte |

## P2 — qualità, operabilità e supply chain

- Introdurre Content-Security-Policy e header di sicurezza per dashboard/API.
- Evitare token in `localStorage` quando il Director diventerà remoto; usare cookie
  `HttpOnly`, `Secure`, `SameSite` con protezione CSRF o un contenitore desktop sicuro.
- Aggiungere lock riproducibile delle dipendenze Python, SBOM, scansione dipendenze e
  secret scanning in CI.
- Rendere la release dipendente esplicitamente dalla CI dello stesso commit e firmare
  provenance/artefatti.
- Aggiungere paginazione a task, audit, approvazioni ed evidenze; eliminare query N+1.
- Aggiungere log JSON strutturati con correlation ID, metriche, alert e nessun dato
  sensibile.
- Documentare e testare backup, ripristino, disaster recovery, rotazione chiavi e
  recupero delle credenziali cifrate.
- Rendere esplicita la parità Mac/Windows: oggi Mac guida il DOM del browser, Windows
  apre il browser e lascia compilazione/login manuali.
- Correggere l'identità utente con vincolo univoco per tenant/email e login non ambiguo.
- Introdurre test di accessibilità e una scansione DAST sull'API locale/remota.

## Coerenza tra documentazione e codice

Le seguenti affermazioni presenti nei documenti attuali sono più forti di ciò che il
codice garantisce:

- “Il kill switch funziona anche a task in corso”: il flag viene ricevuto, ma l'handler
  già avviato non è interrotto.
- “Codice enrollment monouso”: vale per il codice generico, non per gli slot prevedibili
  reinstallabili.
- “Approval token monouso”: l'endpoint usa `token_used`, ma non riceve né verifica un
  token firmato legato al frozen payload.
- “Ogni task è idempotente”: il deduplica soltanto i task vivi; dopo completamento la
  stessa richiesta crea un nuovo task.
- “Audit append-only”: l'API non offre una delete, ma la tabella non ha protezione
  append-only o catena hash.
- “Mask sensitive regions”: la policy lo dichiara, ma `screencapture` fotografa l'intero
  schermo.
- “Licenza autoritativa cloud”: l'owner può usare l'endpoint di simulazione anche senza
  ambiente test.

Queste frasi vanno corrette o rese vere dal codice prima di un documento commerciale o
di produzione.

## Integrazioni: presenti, mancanti e stato sicuro

| Integrazione | Stato reale | Decisione audit |
| --- | --- | --- |
| Grok xAI | Configurabile, chiave cifrata, modello e health check | Utilizzabile per pianificazione test; non dare segreti nel prompt |
| Ollama | Locale, senza API key, health check modelli | Utilizzabile per test locali |
| OpenAI | Configurabile, chiave cifrata, health check | Utilizzabile per pianificazione test |
| GitHub Releases | Controllo e download aggiornamenti | Lettura ammessa; auto-install non production-ready senza firma vendor |
| Webdesk | URL reale non configurato; usa placeholder AdE | Non collegare a clienti reali |
| Agenzia Entrate | Apertura browser/compilazione limitata | Nessun login automatico, nessun invio; mantenere così |
| INPS | Apertura browser; SPID/smart card manuali | Nessun invio; mantenere così |
| CGN | Apertura/browser DOM | Solo prova controllata senza dati reali |
| ComUnica/IPSOA | Schede demo, nessun adapter reale | Non dichiarare come integrazione live |
| F24/PEC/pagamenti | Nessuna esecuzione reale | Restano vietati |
| Fatturazione elettronica reale | Assente | Non implementare prima di Phase 6 e collaudo sandbox |
| Billing | Webhook HMAC proprietario e simulazione | Non è Stripe live; simulazione da isolare ai test |

## Test esistenti e buchi di copertura

La suite attuale ha 172 test verdi e copre Argon2id, configurazione production,
provider IA, policy, alcune query cross-tenant, cifratura Cassaforte/evidenze, grant,
replay del codice generico, uso singolo della lease e doppio click sequenziale
sull'approvazione.

Test bloccanti da aggiungere:

1. manomissione importo 1.000 → 10.000 dopo freeze: approvazione ed esecuzione negate;
2. modifica destinatario, IBAN o scadenza dopo freeze: hash diverso e approvazioni
   invalidate;
3. Agent A prova a inviare risultato per task assegnato ad Agent B: `403`;
4. firma valida del solo task ID ma corpo alterato: negata;
5. replay risultato dopo riavvio Agent/Director: negato;
6. WebSocket Agent senza challenge o con chiave sbagliata: chiusa;
7. enrollment slot riutilizzato senza autorizzazione: negato;
8. kill di tenant A non raggiunge tenant B;
9. kill durante un handler lungo interrompe prima del passo successivo;
10. preparatore prova ad approvare la propria operazione: negato;
11. due approvazioni concorrenti: una sola transizione/esecuzione;
12. retry dopo timeout remoto con stato incerto: nessuna doppia esecuzione;
13. owner prova a riattivare licenza con endpoint demo in production: negato;
14. password/token nel testo chat: il mock provider non riceve il segreto;
15. screenshot con campo sensibile: regione mascherata e nessun invio al modello;
16. artefatto update con checksum coerente ma firma vendor errata: negato;
17. isolamento tenant su WebSocket, audit, receipt, operation e ogni join;
18. feature flag reali assenti: executor risponde fail-closed.

La CI dovrà aggiungere coverage con soglia, test concorrenti, test di migrazione,
dependency audit, secret scan e build/verifica firma dei pacchetti.

## Piano di implementazione a branch separati

### Branch 0.1 — fondazioni P0 di identità e runtime

- segreti unici per installazione desktop;
- bootstrap titolare senza password demo;
- enrollment casuale monouso e reinstallazione autorizzata;
- WebSocket challenge-response e hub per tenant;
- binding stretto dei risultati Agent e firma del corpo;
- kill switch tenant-scoped e cancellazione cooperativa;
- disabilitazione production degli endpoint demo/simulate.

Nessuna integrazione reale viene aggiunta in questo branch.

### Branch 1 — operation core e frozen payload

- migrazioni;
- `Operation`, tipo operazione, stato, versione e correlation ID;
- payload Pydantic canonico e validazione economica/fiscale;
- frozen payload SHA-256 immutabile;
- transizioni DRAFT → UNDER_REVIEW → READY_FOR_APPROVAL;
- audit di ogni transizione.

### Branch 2 — approval gateway e RBAC

- snapshot leggibile e hash;
- approvazione legata a utente, ruolo, payload e scadenza;
- four-eyes, dual approval sopra soglia e invalidazione su modifica;
- UI minima necessaria per mostrare dati, differenze e stato.

### Branch 3 — execution engine e idempotenza

- executor separato dall'IA;
- verifica finale hash/policy/approvazioni/flag;
- idempotency key atomica;
- stati di tentativo e gestione `uncertain`;
- receipt normalizzato e nessun retry cieco.

### Branch 4 — safety engine

- soglie importo e frequenza;
- destinatari nuovi o modificati;
- anomalie, duplicati e rischio contestuale;
- blocco, seconda approvazione e kill switch per integrazione.

### Branch 5 — IA strutturata e prompt security

- schema stretto per ogni proposta IA;
- separazione istruzioni/dati;
- DLP locale;
- tool registry con descrizione, schema input, rischio e policy;
- log delle proposte senza segreti.

### Branch 6 — integrazioni progressive

Una sola integrazione alla volta: sandbox ufficiale, lettura, preparazione bozza,
preview, approvazione, esecuzione controllata, verifica e ricevuta. I flag reali restano
`false` finché ogni test e controllo operativo non è verde.

### Branch 7 — suite di sicurezza

Unit, integration, end-to-end, concorrenza, tamper, replay, tenant isolation, prompt
injection, failure network e double submission.

### Branch 8 — readiness e documentazione

Runbook, backup/restore, rotazione chiavi, incident response, rollout/rollback,
monitoraggio, firma/notarizzazione, privacy e revisione legale. Solo qui si rivaluta
l'eventuale uso reale.

## Criteri di stop/go

`GO` per la prossima fase soltanto se:

- CI obbligatoria verde;
- nessun test di sicurezza regressivo;
- nessuna capability reale nuova;
- migrazione e rollback provati su copia del database;
- audit mostra chi, cosa, quando, tenant e correlation ID;
- interfaccia dichiara chiaramente DEMO o REALE;
- i flag di esecuzione reale sono assenti o `false`.

`STOP` immediato se:

- un payload cambia dopo approvazione senza invalidarla;
- un Agent agisce fuori tenant/task/capability assegnati;
- un segreto compare in prompt, log o evidenza;
- un retry può duplicare un effetto;
- il kill switch non ferma prima del passo successivo;
- un artefatto non prova l'identità del firmatario;
- una funzione demo può raggiungere un sistema reale.

## Conclusione della Fase 0

Il repository ha una buona base dimostrativa: policy dopo il modello, allowlist, cifratura,
tenant filter REST e CI obbligatoria. La documentazione precedente ha però sovrastimato
la forza di enrollment, WebSocket, kill switch, idempotenza, approval token e audit.

La prima modifica successiva non deve collegare nuovi portali o rendere “reali” gli
Agent. Deve chiudere il branch 0.1 di identità/runtime; poi si può costruire l'operation
core con payload congelato. F24, PEC, pagamenti, login SPID/CNS/CIE, fattura elettronica
reale e schermate al modello restano fuori perimetro e vietati.
