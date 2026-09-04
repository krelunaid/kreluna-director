# Browser Kreluna dedicato — stato di sviluppo

Questa modalità controlla un Chromium separato, non il mouse del sistema e non
Safari/Chrome personali. È limitata a `fatture-webdesk` e resta opt-in finché la
prova completa sul portale reale non è conclusa.

## Funzionamento

- Il processo dell'Agent possiede un solo worker browser. Richieste concorrenti
  sono rifiutate, non accodate per un avvio inatteso.
- Ogni attività usa una nuova pagina; non sovrascrive una fattura lasciata aperta.
  Dopo dieci pagine occorre chiudere quelle già revisionate.
- Il profilo è separato per Director/dispositivo, nella cartella dati dell'Agent,
  con permessi locali restrittivi. Non viene copiato il profilo personale.
- Non viene aperta una porta di debugging TCP. Nessuna acquisizione del desktop,
  registrazione di password/codici, download o allegato di schermate ai task.
- Le navigazioni sono limitate a HTTPS sui quattro host Webdesk/Genya noti.
  Nuove finestre non diventano automaticamente la destinazione dei comandi.
- Se la pagina cambia sito o viene chiusa, il lavoro si ferma; non passa al mouse
  o a Safari. Soltanto le letture possono essere ritentate durante una navigazione.
- Salva, Emetti, Invia, Trasmetti e Paga restano vietati nelle azioni fattura.
  La richiesta del codice di accesso è un'azione distinta con controlli specifici.

Non è un secondo puntatore del Mac: gli eventi avvengono nella pagina del browser.
L'utente può usare il proprio browser; non deve modificare la pagina che Kreluna
sta compilando. Questo non equivale a una macchina virtuale né garantisce il
funzionamento con computer spento, sospeso o sessione disconnessa.

## Preparazione sviluppatore

Installare l'extra `browser` del progetto e il Chromium compatibile con Playwright.
Impostare `KRELUNA_WEBDESK_BROWSER=dedicated` nel processo dell'Agent per abilitare
la modalità. In assenza del motore viene restituito un errore esplicito.

Il codice riconosce un eventuale bundle `Contents/Resources/browser-runtime`.
L'inclusione nell'installer non è ancora conclusa: Playwright introduce greenlet,
che richiede la verifica delle librerie native Apple Silicon. Gli installer
attuali non abilitano questa modalità; non dichiararli pronti sulla base dei test.

## Verifica

`KRELUNA_TEST_BROWSER=1 .venv/bin/python -m pytest tests/integration/test_dedicated_browser_real.py -q`

La prova usa Chromium reale ma risposte HTML intercettate: verifica scrittura,
clic, separazione delle schede, rifiuto di altri siti e blocco del salvataggio.
Non dimostra la compilazione di una fattura vera.

`scripts/check-webdesk-gmail-local.py --dedicated` verifica soltanto il login reale,
con task/database isolati e credenziali locali già cifrate. Non prepara fatture.
Non avviare Director/Agent con la coda reale per eseguire questo controllo.

## Esito locale del 4 settembre

Due prove Chromium con fixture passate; suite generale 377 passati, due prove
browser opt-in saltate nell'esecuzione normale. La prova Webdesk reale supera il
login, richiede il codice e raggiunge la compilazione della validazione, ma non
ha ancora confermato il ritorno alla dashboard. Non è una prova end-to-end riuscita.
Il browser dedicato non è stato attivato nell'app installata.

La suite generale ha inoltre rivelato un vecchio test che apriva materialmente il
simulatore fatture sul desktop. La finestra e il relativo avvio sono stati rimossi
dal repository e dall'Agent installato. I vecchi entry point ora rifiutano
esplicitamente l'esecuzione; i nuovi test verificano che non esista più la finestra.
