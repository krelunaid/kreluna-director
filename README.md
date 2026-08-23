# Kreluna Director

IA centrale dello studio: **tu parli solo con il Director**. Lui decide quali PC servono, manda task strutturati, raccoglie prove e ti chiede approvazione prima delle azioni sensibili.

Questa versione parte dal piano Codex e la rende usabile: contratti tipizzati, policy più forte del modello, agent anche su Linux, gestionale DEMO interno, dashboard in italiano.

## Cosa fa

```
Tu → Director (planner + policy) → Agent sul PC → evidenza → tu approvi → esecuzione
```

Esempi che capisce già:

- `Apri Blocco Note e scrivi: Kreluna Agent operativo`
- `Prepara una fattura demo a Rossi Mario per consulenza, EUR 1500 + IVA`
- `Controlla quali clienti hanno documenti mancanti`
- `Ferma tutto`

## Cosa non fa (di proposito)

- Nessuna shell remota, nessun `eval` di output IA
- Nessun invio F24 / PEC / pagamento reale
- Nessuna licenza `paid=true` sul PC
- Nessun sequestro di Windows o dei file del cliente se manca il pagamento

## Avvio

```bash
make demo
```

Poi apri [http://127.0.0.1:5173](http://127.0.0.1:5173)

Login demo: `andrea@studio.demo` / `demo`

## Test

```bash
python3 -m pip install -e ".[dev]"
make test
```

## Architettura

Vedi `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/THREAT_MODEL.md`, `docs/IMPROVEMENTS.md`.

Stack: FastAPI + SQLite + React. L’Agent Windows usa `pywinauto` se c’è; altrimenti un notepad virtuale con screenshot PNG, stesso contratto.
