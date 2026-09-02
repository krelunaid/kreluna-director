# Percorso IPSOA Webdesk per clienti e fatture

Questa mappa descrive il percorso operativo osservato nel manuale dello studio.
Non contiene credenziali e non autorizza il salvataggio o l'invio di dati reali.

## 1. Accesso e scelta del cliente

1. Aprire IPSOA e accedere a Webdesk con l'utenza autorizzata.
2. Aprire **Servizi SMART**.
3. In **Accesso Servizi SMART**, scegliere il criterio di ricerca:
   **Codice**, **Denominazione** oppure **Codice fiscale**.
4. Scrivere il valore nel campo **Contiene** e controllare la riga restituita.
5. Verificare denominazione, codice fiscale e Partita IVA.
6. Se la corrispondenza e corretta, usare **Accedi**.

Kreluna non deve scegliere una riga ambigua: in presenza di piu risultati si
ferma e chiede quale cliente usare.

## 2. Cliente non presente

1. Aprire **Clienti** e poi **Crea nuovo**.
2. Scegliere la tipologia corretta: privato, persona fisica titolare di Partita
   IVA oppure soggetto diverso da persona fisica.
3. Compilare almeno codice fiscale o Partita IVA, denominazione oppure nome e
   cognome, sede legale e codice destinatario SDI. PEC e altri recapiti vanno
   aggiunti quando disponibili.
4. Controllare i dati e fermarsi prima di **Salva**. La creazione dell'anagrafica
   richiede la conferma dell'operatore.

## 3. Preparazione della fattura

1. Tornare a **Home**, aprire **Fatture** e scegliere **Crea nuovo**.
2. Selezionare tipo documento e cliente; compilare numero/riferimento, data,
   scadenza e modalita di pagamento quando richiesti.
3. Inserire descrizione, quantita, unita, imponibile, sconto e IVA nelle righe.
4. Controllare imponibile, imposta e totale.
5. Fermarsi prima di **Salva**, **Emetti**, **Invia** o trasmettere allo SDI.

## 4. Pagine da insegnare all'Agent

Sul PC che usa davvero Webdesk, aprire una pagina alla volta e chiedere
`impara la pagina di Webdesk`:

1. Accesso Servizi SMART / ricerca cliente.
2. Elenco Clienti con il comando Crea nuovo.
3. Modulo Nuovo cliente.
4. Modulo Nuova fattura.

Le fotografie mostrano etichette e sequenza, ma non gli identificatori DOM
stabili. I selettori vanno acquisiti dalla pagina reale e salvati in
`policies/programs.yaml`. I pulsanti finali di salvataggio e invio restano
esclusi dall'esecuzione automatica.
