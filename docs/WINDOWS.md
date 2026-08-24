# Kreluna Director sul PC Windows

Non è un sito da telefono. È un’**app per computer Windows**.

## Installazione

1. Scarica `Kreluna-Director-Windows.zip`
2. Estrailo (tasto destro → Estrai tutto)
3. Doppio clic su **Installa.bat**
4. Se Windows blocca: **Altre informazioni** → **Esegui comunque**
5. La prima volta serve **Python 3.11+**: [python.org/downloads/windows](https://www.python.org/downloads/windows/)  
   Spunta **Add python.exe to PATH**.

L’app va in `%LOCALAPPDATA%\KrelunaDirector` (cartella utente, senza amministratore). Sul desktop compare il collegamento.

## Accesso

- Indirizzo (si apre da sola): `http://127.0.0.1:8080`
- Email: `andrea@studio.demo`
- Password: `demo`

## Agent su un altro PC dello studio

Dallo stesso zip, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-KrelunaAgent.ps1 -Role pc-fatture -DirectorUrl http://IP-DEL-DIRECTOR:8080 -EnrollCode KRELUNA-PC-FATTURE
```

Un ruolo per PC. I programmi gestionali restano **da definire**.

## Ricreare lo zip

```bash
make windows
```

Il file esce in `dist-windows/Kreluna-Director-Windows.zip`.
