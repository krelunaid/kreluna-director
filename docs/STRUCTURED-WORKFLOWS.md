# Schede operative strutturate — v0.5.35

Fatture, F24, contabilità, pratiche camerali, contratti, DURC e visure non sono
più trattati come semplici frasi o schede dimostrative. Ogni Agent restituisce
una bozza locale leggibile dal Director con:

- cliente e tipo di lavoro;
- dati forniti dall'operatore e dati calcolati localmente;
- programma e percorso configurato;
- passaggi che l'Agent può preparare;
- dati mancanti e stato `validata` / `da completare`;
- portali ordinari che possono richiedere un accesso in Fort Knox;
- barriere esplicite prima di invio, firma, pagamento o download definitivo.

## Confine tra IA e regole locali

Il modello IA interpreta l'italiano e propone un task. Non decide la validità
del lavoro e non può aggiungere cliente, periodo, tipo di contratto, tipo di
pratica o tipo di visura se quel dettaglio non compare nella richiesta. I
modelli ammessi e la validazione risiedono nel pacchetto condiviso locale.

Le password non vengono inviate all'IA. La bozza contiene soltanto il nome dei
portali necessari. Quando l'operatore chiede esplicitamente di aprire un sito
vero usando l'accesso salvato, la credenziale viene consegnata una sola volta
all'Agent già assegnato, tramite il canale autenticato esistente.

## Azioni che restano escluse

- invio di fatture, F24, PEC o pratiche;
- pagamenti e acquisti;
- firma digitale automatica;
- login automatico SPID, CNS, CIE o smart card;
- uso automatico di OTP;
- download definitivo senza controllo della persona;
- invio di schermate all'IA.

Le schede sono anteprime operative. Per completare un portale reale occorrono
il suo link configurato, la mappa dei campi e, quando previsto, l'intervento
umano per autenticazione e conferma.
