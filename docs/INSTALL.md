# Installa Kreluna Director

App per **Mac** e **Windows**. Non è un sito da telefono. **Non serve Python.**

Il **Director funziona anche senza Agent installati**: mostra i sette ruoli come
"Da installare" e permette di usare dashboard, richieste, regole e configurazione IA.
Gli Agent sono programmi separati e si aggiungono in seguito, uno per computer.

## Mac

1. Apri `Kreluna-Director-Mac.zip`
2. Trascina `Kreluna Director.app` sulla cartella **Applicazioni**
3. Finestra gialla: **Fine** (non Cestino) → Impostazioni di Sistema → Privacy e sicurezza → **Apri comunque**

Dettagli: `docs/MAC.md`.

## Windows (PC)

1. Apri `Kreluna-Director-Windows.zip`
2. Doppio clic su **Installa.bat**
   Se Windows avvisa: Altre informazioni → Esegui comunque
3. Sul desktop compare **Kreluna Director**

Dettagli: `docs/WINDOWS.md`.

## Agent (programma a parte dal Director)

- **Mac:** `Kreluna-Agent-Mac.zip` → trascina **Kreluna Agent** in Applicazioni → scegli il ruolo (PC-FATTURE, …)
- **Windows:** `Kreluna-Agenti-Windows.zip` → **Installa PC-FATTURE.bat** (un file per PC)

Un Agent per computer. Non è il cervello.

## Accesso

- Si apre da sola la finestra su `http://127.0.0.1:8080`
- Email: `andrea@studio.demo`
- Password: `demo`

## Aggiornamenti (anche se è già installata)

1. **Chiudi** Kreluna
2. Apri lo zip nuovo
3. Stesso installatore di prima
4. Riapri Kreluna

Il programma viene sostituito. **I dati restano.**

Ricreare gli zip:

```bash
make installers
```
