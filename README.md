# Kreluna Director

IA centrale dello studio: **tu parli solo con il Director**. Lui decide quali PC servono, manda task strutturati, raccoglie prove e ti chiede approvazione prima delle azioni sensibili.

## Installa sul computer (Mac o Windows)

Istruzioni: `docs/INSTALL.md`

- Mac Director: `Kreluna-Director-Mac.zip` → trascina `Kreluna Director.app` in Applicazioni
- Mac Agent: `Kreluna-Agent-Mac.zip` → `Kreluna Agent.app` (scegli il ruolo)
- Windows Director: `Kreluna-Director-Windows.zip` → **Installa.bat**
- Windows Agent: `Kreluna-Agenti-Windows.zip` → **Installa PC-FATTURE.bat** (ecc.)

**Non serve installare Python.** È già dentro il programma.

Il Director usa una finestra nativa propria: Chrome, Safari o Edge non servono
per aprire Kreluna. Il motore locale e l'indirizzo `127.0.0.1` restano interni
all'app; un browser viene aperto soltanto quando un Agent deve lavorare su un
portale esterno.

Il Director è autonomo: gli Agent sono opzionali e si installano separatamente
quando vuoi collegare i PC operativi.

L'app installata crea al primo avvio credenziali personali casuali e le mostra una
sola volta. Le credenziali `*.demo` esistono soltanto nell'ambiente di sviluppo.

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
- `Prepara F24 ordinario IVA trimestrale secondo trimestre per Andrea Gadducci, anno 2026, debito 1.250 euro`
- `Scarica le fatture in IPSOA per Gadducci`
- `Apri il sito CGN e fai la visura vera per Gadducci` (browser vero sul Mac)
- `Apri il sito CGN per Gadducci usando l'accesso salvato` (compila, non accede)
- `Cosa sai fare?`
- `Ferma tutto`

## Kreluna Fort Knox

Da **Fort Knox** il titolare può inserire un cliente direttamente oppure importare
un CSV con cliente, portale, username e password/token. Il Director valida i dati,
deriva una chiave distinta per lo studio, cifra ogni accesso e mostra soltanto
valori mascherati. Grok/OpenAI/Ollama non ricevono moduli, CSV o credenziali.
Configurazione e requisiti del servizio centrale: [`docs/FORT-KNOX.md`](docs/FORT-KNOX.md).

`portal_open` guida il browser del Mac: apre il portale, aspetta il login umano,
controlla che la pagina davanti sia davvero quella del portale, scrive nel campo
trovato per nome (non a coordinate del mouse) e si ferma. Indirizzi e campi
stanno in `policies/programs.yaml`, correggibili senza toccare il codice.
Se viene richiesto esplicitamente l'accesso salvato, compila username e password
ma non clicca **Accedi** e non cattura una schermata dopo la compilazione.

## IA inclusa

Grok `grok-4.6` è incluso tramite il gateway Kreluna: il cliente non inserisce
e non riceve la chiave xAI. Ogni installazione usa una licenza distinta,
revocabile e soggetta a quota; la chiave principale resta soltanto sul servizio
centrale. OpenAI e Ollama restano selezionabili come alternative configurabili.
La dashboard mostra sempre una diagnostica esplicita, senza passare in silenzio
a un altro provider. Dettagli operativi: `docs/MANAGED-AI-GATEWAY.md`.

Il modello propone, la policy decide. Non può usare capability fuori elenco,
non può inventare o cambiare un importo o un cliente che non sia nella frase
del titolare, e non decide da sé cosa non ha bisogno di approvazione.

L'Agente F24 prepara bozze strutturate per Ordinario, Semplificato, ELIDE,
Accise ed Enti pubblici. I codici automatici sono limitati al catalogo ufficiale
locale versionato; gli altri devono essere indicati dall'operatore. Dettagli e
limiti: [`docs/F24-ENGINE.md`](docs/F24-ENGINE.md).

Anche fatture, contabilità, camerali, contratti, DURC e visure producono una
scheda strutturata con dati forniti, percorso, passaggi e informazioni mancanti.
Il Director la mostra prima di qualsiasi operazione definitiva. Dettagli:
[`docs/STRUCTURED-WORKFLOWS.md`](docs/STRUCTURED-WORKFLOWS.md).

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

Il programma controlla le release ufficiali e avvisa se c’è una versione nuova. Su Mac
e Windows, da **Aggiornamento → Installa ora**, verifica il pacchetto, sostituisce
l’app e si riapre; i dati restano. Dettagli: `docs/INSTALL.md`.

## Collegare un Agent

Sulla scheda gialla **Da installare** premi l'interruttore: il Director genera un
codice casuale valido 20 minuti e una sola volta. Inseriscilo nell'installer Mac o
Windows del PC scelto. Il Director conserva soltanto l'impronta del codice. Un PC
già collegato non può essere sostituito finché il titolare non lo revoca.

## Test

```bash
python3 -m pip install -e ".[dev]"
make test
```

## Architettura

Vedi `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/THREAT_MODEL.md`, `docs/IMPROVEMENTS.md`.

Stack: FastAPI + SQLite + React, finestra nativa WKWebView su Mac e WebView2 su
Windows. L’Agent Windows usa `pywinauto` se c’è; altrimenti un notepad virtuale
con screenshot PNG, stesso contratto.
