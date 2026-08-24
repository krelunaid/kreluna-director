# Kreluna Director sul Mac

Non è un sito da iPhone. È un’**app per computer Mac** (macOS).

## Installazione

1. Scarica `Kreluna-Director-Mac.zip`
2. Aprilo (doppio clic)
3. Doppio clic su **Installa Kreluna.command**
   - oppure trascina `Kreluna Director.app` in **Applicazioni**
4. Se macOS blocca l’app: clic destro → **Apri** → **Apri**
5. La prima volta serve **Python 3.11+**: [python.org/downloads/macos](https://www.python.org/downloads/macos/)

## Accesso

- Indirizzo (si apre da sola): `http://127.0.0.1:8080`
- Email: `andrea@studio.demo`
- Password: `demo`

## Cosa vedi

Chat con il Director, il Mac come PC-studio, fattura demo, screenshot, Approva/Rifiuta.

Non invia F24 veri. Per i gestionali italiani dello studio serve in seguito un PC Windows.

## Ricreare lo zip

```bash
make mac
```

Il file esce in `dist-macos/Kreluna-Director-Mac.zip`.

Istruzioni complete Mac + Windows: `docs/INSTALL.md`.
