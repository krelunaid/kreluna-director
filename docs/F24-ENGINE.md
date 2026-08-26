# Agente F24 — preparazione controllata

Kreluna 0.5.34 sostituisce la vecchia scheda dimostrativa F24 con una bozza
strutturata e validata localmente. Grok interpreta la frase dell'operatore, ma
non può trasmettere il modello, avviare il pagamento o inventare un codice
tributo.

## Modelli supportati

- F24 ordinario;
- F24 semplificato;
- F24 ELIDE;
- F24 Accise;
- F24 Enti pubblici.

Il motore verifica la compatibilità fra modello e sezione, anno e forma dei
codici, esclusività fra debito e credito sulla singola riga, campi specifici
Accise e saldo complessivo. La bozza mostra sempre `sent=false`,
`payment_started=false` e `requires_human_approval=true`.

## Codici automatici

Il catalogo locale versionato contiene soltanto regole verificate nella ricerca
guidata dell'Agenzia delle Entrate:

- IVA mensile 6001–6012 e acconto 6013;
- IVA trimestrale 6031–6034 e acconto 6035;
- ritenute su retribuzioni 1001;
- ritenute su lavoro autonomo 1040.

Per queste causali l'IA propone una `rule_key`; il codice viene risolto dal
motore locale. Per tutte le altre causali il codice tributo deve comparire nella
richiesta o provenire in futuro da una tabella ufficiale aggiornata. Se Grok
propone un codice, anno o importo non presente nei dati forniti, il task non
viene creato.

Fonte del catalogo: <https://www1.agenziaentrate.gov.it/servizi/codici/ricerca/>.
Versione regole: `ade-2026-03-26`.

## Percorso operativo

1. L'operatore indica cliente, modello, causale/tributo, anno e importo.
2. Grok produce soltanto dati strutturati nell'ambito dello studio.
3. La policy e il motore F24 ricontrollano tutto in modo deterministico.
4. PC-F24 crea una bozza e una prova visibile.
5. In `Task` si usa **Apri bozza** per controllare righe e totali.
6. Nessuna funzione del programma preme Invio Telematico o avvia pagamenti.

Il portale `F24 — IPSOA` è assegnato a PC-F24. Il relativo indirizzo e le
credenziali possono essere conservati in Fort Knox; l'Agent può compilare i
campi di accesso solo su richiesta esplicita e si ferma prima del login. SPID,
CNS, CIE, smart card e OTP restano sempre manuali.
