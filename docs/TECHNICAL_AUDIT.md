# Audit tecnico — 25 agosto 2026

Base verificata: `cursor/kreluna-director-381b` (`2253a42`). L'audit ha coperto
configurazione e avvio, autenticazione, planner IA, API e isolamento tenant, stato task,
dashboard, dipendenze, policy/capability degli Agent, test e build.

## Bug reali trovati e corretti

| Priorità | Evidenza | Impatto | Correzione |
| --- | --- | --- | --- |
| P0 | I segreti avevano placeholder accettati in ogni ambiente e l'avvio creava utenti `demo` | Un deploy production poteva partire con credenziali note | Validazione fail-closed, segreti distinti >=32 caratteri, bootstrap production esplicito, rifiuto di database con dati demo |
| P0 | `hash_password` usava SHA-256 con un segreto globale | Hash troppo veloce e senza sale individuale | Argon2id (64 MiB, 3 iterazioni, parallelismo 4, sale casuale) e migrazione trasparente degli hash esistenti al login |
| P0 | Errori HTTP, timeout e risposte IA malformate tornavano `None` | Il planner usava silenziosamente la risposta deterministica e nascondeva il guasto | Diagnostica esplicita, nessun task creato, codice errore strutturato e audit `planner.ai_error` |
| P0 | `make lint` terminava sempre con successo e non esisteva CI | Regressioni potevano essere unite senza controlli | Lint bloccante e workflow GitHub Actions con lint, test e build |
| P0 | SQLAlchemy async non dichiarava `greenlet` | 25 test database fallivano su installazione pulita | Dipendenza `sqlalchemy[asyncio]` |
| P0 | Test Mac dichiarato Linux senza simulare la piattaforma | Suite locale rossa su macOS | Piattaforma isolata nel test |
| P0 | Vite 5.4.21 risultava vulnerabile nel controllo npm | Server di sviluppo esposto a path traversal/divulgazione | Toolchain aggiornata; `npm audit` a zero vulnerabilità |
| P1 | Un solo trio URL/chiave/modello e chiave obbligatoria | Configurazioni mescolabili; Ollama non poteva risultare pronto senza chiave fittizia | Config separate Grok/Ollama/OpenAI, selezione persistente per studio e compatibilità con le variabili precedenti |
| P1 | `ai_connected` indicava solo la presenza di variabili | Provider o modello potevano essere irraggiungibili mentre la UI mostrava “collegata” | Health check autenticato e in cache che verifica endpoint e modello |
| P1 | Il contatore “Errori” non esponeva lo storico; `tasks_today` contava tutti i task | Stato operativo ambiguo e conteggio giornaliero errato | Errori attivi (24 ore) separati dallo storico e conteggio task sulla stessa finestra |

## Invarianti di sicurezza riesaminate

- Nessuna capability di shell remota e nessun `eval` sono stati aggiunti.
- `invoice_submit`, `invoice_submit_demo`, pagamenti, PEC e invii reali restano negati
  dalla policy; le capability disponibili preparano soltanto bozze.
- SPID, CNS e smart card restano passaggi manuali dell'utente.
- Il planner IA riceve soltanto il testo digitato. Gli screenshot restano evidenze cifrate
  e non entrano né nel prompt né nelle richieste di health check.
- Il selettore provider non espone né salva chiavi API nel database o nel browser: salva
  soltanto `grok`, `ollama` oppure `openai`.

## Limiti residui dichiarati

Restano fuori da questo intervento notarizzazione/code signing, penetration test
indipendente, certificazioni e adapter fiscali reali. Non sono state abilitate operazioni
reali: il prodotto conserva esplicitamente i limiti descritti in `docs/PRODUCTION.md`.
