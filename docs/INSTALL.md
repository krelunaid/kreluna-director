# Installa Kreluna Director

App per **Mac** e **Windows**. Non è un sito da telefono.

## Mac

1. Apri `Kreluna-Director-Mac.zip`
2. Doppio clic su **Installa Kreluna.command**
   (oppure trascina `Kreluna Director.app` in Applicazioni)
3. Se macOS blocca: clic destro → **Apri** → **Apri**
4. Serve **Python 3.11+**: https://www.python.org/downloads/macos/

Dettagli: `docs/MAC.md`.

## Windows (PC)

1. Apri `Kreluna-Director-Windows.zip`
2. Doppio clic su **Installa.bat**
   Se Windows avvisa: Altre informazioni → Esegui comunque
3. Sul desktop compare **Kreluna Director**
4. Serve **Python 3.11+** con PATH: https://www.python.org/downloads/windows/

Dettagli: `docs/WINDOWS.md`.

## Accesso

- Si apre da sola la finestra su `http://127.0.0.1:8080`
- Email: `andrea@studio.demo`
- Password: `demo`

## Aggiornamenti

All’avvio Kreluna legge `GET /update/manifest` (firma Ed25519).  
Se esce una versione più nuova **ti avvisa**. Non scarica zip da sola.

Quando gli zip saranno su un indirizzo pubblico, nel `.env`:

```
KRELUNA_UPDATE_URL=https://tuo-canale/update/manifest
KRELUNA_UPDATE_MAC_URL=https://…/Kreluna-Director-Mac.zip
KRELUNA_UPDATE_WIN_URL=https://…/Kreluna-Director-Windows.zip
KRELUNA_UPDATE_MAC_SHA256=…
KRELUNA_UPDATE_WIN_SHA256=…
```

Ricreare gli zip:

```bash
make installers
```

Escono in `dist-macos/` e `dist-windows/`.
