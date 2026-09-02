# Installa Kreluna Director

App per **Mac** e **Windows**. Non è un sito da telefono. **Non serve Python.**

Il Director si apre in una finestra propria con l'icona K: non usa Chrome,
Safari o Edge per mostrare la dashboard. I browser restano separati e vengono
aperti soltanto dagli Agent quando un lavoro richiede un portale esterno.

Il **Director funziona anche senza Agent installati**: mostra i sette ruoli come
"Da installare" e permette di usare dashboard, richieste, regole e configurazione IA.
Gli Agent sono programmi separati e si aggiungono in seguito, uno per computer.

## Mac

1. Apri `Kreluna-Director-Mac.zip`
2. Trascina `Kreluna Director.app` sulla cartella **Applicazioni**
3. Finestra gialla: **Fine** (non Cestino) → Impostazioni di Sistema → Privacy e sicurezza → **Apri comunque**

Per cancellare completamente programma e dati, apri lo ZIP e avvia
**Disinstalla Kreluna.command**; dopo la conferma sposta tutto nel Cestino.

Dettagli: `docs/MAC.md`.

## Windows (PC)

1. Apri `Kreluna-Director-Windows.zip`
2. Doppio clic su **Installa.bat**
   Se Windows avvisa: Altre informazioni → Esegui comunque
3. Sul desktop compare **Kreluna Director**

Dettagli: `docs/WINDOWS.md`.

## Agent (programma a parte dal Director)

1. Nel Director premi l'interruttore della scheda gialla **Da installare** e copia
   il codice monouso. Il codice vale 20 minuti ed è legato a quel preciso ruolo.
2. **Mac:** `Kreluna-Agent-Mac.zip` → trascina **Kreluna Agent** in Applicazioni →
   scegli lo stesso ruolo e incolla il codice.
3. **Windows:** `Kreluna-Agenti-Windows.zip` → **Installa PC-FATTURE.bat** (o il
   ruolo scelto) → incolla il codice quando viene richiesto.

Un Agent per computer. Non è il cervello.

I pacchetti ufficiali includono tutti e sette i lavori su entrambi i sistemi:
Fatture, F24, Contabilità, Camerali, Contratti, DURC e Visure. Sul Mac scegli
il lavoro al primo avvio; nello zip Windows c'è un pulsante di installazione per ogni lavoro.

Se l'Agent è su un computer diverso dal Director, configura un indirizzo **HTTPS**.
L'indirizzo HTTP è accettato soltanto quando Director e Agent sono sullo stesso computer.

## Kreluna Fort Knox

1. Apri **Fort Knox** nella barra laterale.
2. Premi **Nuovo cliente**, inserisci portale e accesso, quindi scegli **Cifra e salva**.
3. Per molti clienti puoi usare **Scarica modello** e **Importa CSV**.
4. SPID, CNS, CIE, smart card e OTP non possono essere salvati.
5. Per compilare un accesso senza effettuare il login, chiedi ad esempio:
   `Apri il sito CGN per Bianchi usando l'accesso salvato`.

Il CSV non viene conservato dal Director e non viene inviato al provider IA.
L'Agent inserisce i campi e si ferma: il click su **Accedi**, l'OTP e ogni invio restano umani.

## Collegare Grok

Apri **Impostazioni**, scegli **Grok (xAI)**, lascia `grok-4.6` come modello,
incolla la chiave API xAI e premi **Salva e controlla**. La chiave viene cifrata
nel database locale e la schermata non può rileggerla. Solo il titolare può
cambiare questa configurazione.

## Accesso

- Si apre da sola la finestra **Kreluna Director**; l'indirizzo locale resta interno
- Al primo avvio il programma mostra email e password personali casuali una sola volta
- Conservale: il pacchetto installabile non contiene account o password demo

## Aggiornamenti (anche se è già installata)

### Mac

1. Quando il pallino sotto **Impostazioni** diventa rosso, premi **Aggiornamento**
2. Premi **Installa ora**
3. Kreluna verifica il file, sostituisce l'app in **Applicazioni** e si riapre

Se l'app non è in Applicazioni o il Mac non concede il permesso, Kreluna mostra
un errore esplicito e lascia disponibile **Scarica manualmente**.

### Windows

1. Quando compare il pallino rosso, premi **Aggiornamento**
2. Premi **Installa ora**
3. Kreluna verifica lo ZIP ufficiale, aggiorna il programma e si riapre

Se il PC impedisce l'installazione automatica, resta disponibile **Scarica manualmente**.
Il programma viene sostituito. **I dati, i documenti e la configurazione IA restano.**

Ricreare gli zip:

```bash
make installers
```
