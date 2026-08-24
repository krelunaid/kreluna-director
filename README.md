# Kreluna Director

IA centrale dello studio: **tu parli solo con il Director**. Lui decide quali PC servono, manda task strutturati, raccoglie prove e ti chiede approvazione prima delle azioni sensibili.

## Installa sul computer (Mac o Windows)

Istruzioni: `docs/INSTALL.md`

- Mac Director: `Kreluna-Director-Mac.zip` → trascina `Kreluna Director.app` in Applicazioni
- Mac Agent: `Kreluna-Agent-Mac.zip` → `Kreluna Agent.app` (scegli il ruolo)
- Windows Director: `Kreluna-Director-Windows.zip` → **Installa.bat**
- Windows Agent: `Kreluna-Agenti-Windows.zip` → **Installa PC-FATTURE.bat** (ecc.)

**Non serve installare Python.** È già dentro il programma.

Login demo: `andrea@studio.demo` / `demo`

Per ricreare gli zip:

```bash
make installers
```

## Cosa fa

```
Tu → Director (planner + policy) → Agent sul PC → evidenza → tu approvi → esecuzione
```

Un PC, un lavoro, un programma (`policies/agents.yaml`):

| PC | Lavoro | Programma |
| --- | --- | --- |
| PC-FATTURE | Fatture | Webdesk e sito Agenzia delle Entrate |
| PC-F24 | Deleghe F24 | Creazione IPSOA, poi Invio Telematico |
| PC-CONTABILITA | Contabilità | Scarico AdE XML/P7M, carico IPSOA, importatore |
| PC-CAMERALI | Pratiche camerali | Sito CGN, poi Desktop ComUnica |
| PC-CONTRATTI | Contratti | Sito Agenzia delle Entrate di Samuele |
| PC-DURC | Richieste DURC | Sito INPS |
| PC-VISURE | Visure | Sito CGN |

Esempi che capisce già:

- `Fai la fattura ad Andrea Gadducci per 35-40 mila euro di manodopera`
- `Prepara gli F24 in scadenza, ma non inviarli`
- `Scarica le fatture in IPSOA per Gadducci`
- `Apri il sito CGN e fai la visura vera per Gadducci` (browser vero sul Mac)
- `Cosa sai fare?`
- `Ferma tutto`

## Lavoro vero sui portali

`portal_open` guida il browser del Mac: apre il portale, aspetta il login umano,
controlla che la pagina davanti sia davvero quella del portale, scrive nel campo
trovato per nome (non a coordinate del mouse) e si ferma. Indirizzi e campi
stanno in `policies/programs.yaml`, correggibili senza toccare il codice.

## IA opzionale

Senza chiave il Director lavora a regole. Con tre righe in `.env`
(`KRELUNA_LLM_BASE_URL`, `KRELUNA_LLM_API_KEY`, `KRELUNA_LLM_MODEL`) capisce
anche l'italiano parlato: vale Grok, OpenAI, o un modello locale in studio.
Dettagli: `docs/COLLEGA-IA.txt`.

Il modello propone, la policy decide. Non può usare capability fuori elenco,
non può inventare o cambiare un importo o un cliente che non sia nella frase
del titolare, e non decide da sé cosa non ha bisogno di approvazione.

## Cosa non fa (di proposito)

- Nessuna shell remota, nessun `eval` di output IA
- Nessun invio F24 / PEC / pagamento reale, nessun click su Invio nei portali
- Nessun login automatico con SPID, CNS o smart card: le credenziali personali le usa l'umano
- Nessuna schermata mandata al modello IA: al modello va solo la frase scritta dal titolare
- Nessuna licenza `paid=true` sul PC
- Nessun sequestro di Windows o dei file del cliente se manca il pagamento

## Avvio in sviluppo

```bash
make demo
```

Poi apri [http://127.0.0.1:5173](http://127.0.0.1:5173)

## Aggiornamenti

Il programma legge `GET /update/manifest` e avvisa se c’è una versione nuova. Per applicarla: chiudi Kreluna e reinstalla lo zip nuovo (i dati restano). Dettagli: `docs/INSTALL.md`.

## Test

```bash
python3 -m pip install -e ".[dev]"
make test
```

## Architettura

Vedi `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/THREAT_MODEL.md`, `docs/IMPROVEMENTS.md`.

Stack: FastAPI + SQLite + React. L’Agent Windows usa `pywinauto` se c’è; altrimenti un notepad virtuale con screenshot PNG, stesso contratto.
