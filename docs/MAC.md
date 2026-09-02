# Kreluna Director sul Mac

Non è un sito da iPhone. È un’**app per computer Mac**.

**Non serve installare Python.** È già dentro il programma.

Non è necessario installare subito gli Agent. Kreluna Director si apre e funziona
da solo; i riquadri dei PC restano su **Da installare** finché non colleghi gli Agent.

Su macOS nuovo la finestra gialla ha solo **Sposta nel Cestino** e **Fine**. Non c’è Apri. Non è rotta.

## Installazione

1. Scarica e apri `Kreluna-Director-Mac.zip`
2. Trascina `Kreluna Director.app` sulla cartella **Applicazioni** (nello zip)
3. Aprila. Se esce la finestra gialla: premi **Fine** (non Cestino)
4. Menu Mela → **Impostazioni di Sistema** → **Privacy e sicurezza**
5. In basso: Kreluna è stata bloccata → **Apri comunque**

## Accesso

- Al primo avvio Kreluna mostra una sola volta email e password personali casuali
- Conservale in un posto sicuro: il pacchetto non contiene password demo

## Aggiornamento

Quando compare il pallino rosso, premi **Aggiornamento → Installa ora**. Kreluna
verifica il pacchetto ufficiale, sostituisce l'app e si riapre. I dati restano.

## Agent su un altro Mac dello studio

1. Sul Director apri **PC & Feature**, scegli il tipo di lavoro e premi **Installa Agent**
2. Premi **Copia collegamento**
3. Sul nuovo Mac trascina `Kreluna Agent.app` in **Applicazioni** e aprilo
4. Incolla l'unico Codice di collegamento richiesto

Il codice contiene già indirizzo e ruolo del PC. Il pallino del PC diventa verde nel
Director appena l'Agent completa il collegamento autenticato.

## Disinstallazione completa

Apri lo ZIP originale e fai doppio clic su **Disinstalla Kreluna.command**. Dopo una
conferma esplicita vengono spostati nel Cestino:

- `/Applications/Kreluna Director.app`
- database, documenti, accessi cifrati e chiave IA
- cache e preferenze locali del Director

Per rendere definitiva la cancellazione, svuota il Cestino. Gli Agent restano installati
perché sono applicazioni separate e possono trovarsi su altri computer.
