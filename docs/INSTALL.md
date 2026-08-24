# Installa Kreluna Director

App per **Mac** e **Windows**. Non è un sito da telefono. **Non serve Python.**

## Mac

1. Apri `Kreluna-Director-Mac.zip`
2. Clic **destro** su **Installa Kreluna.command** → **Apri** → **Apri**
   (se dice Cestino: è il blocco Apple, non è rotta)

Dettagli: `docs/MAC.md`.

## Windows (PC)

1. Apri `Kreluna-Director-Windows.zip`
2. Doppio clic su **Installa.bat**
   Se Windows avvisa: Altre informazioni → Esegui comunque
3. Sul desktop compare **Kreluna Director**

Dettagli: `docs/WINDOWS.md`.

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
