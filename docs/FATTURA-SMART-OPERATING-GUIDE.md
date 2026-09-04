# Fattura SMART: riferimento operativo dell'Agent

Verifica fonti: 4 settembre 2026. Prodotto: Wolters Kluwer / Genya,
accessibile da Webdesk. Non usare le guide omonime Aruba o TeamSystem.

## Fonti e limiti

- [Wolters Kluwer, E-fatture? Fattura Smart!](https://www.wolterskluwer.com/it-it/expert-insights/e-fatture-fattura-smart): conferma la gestione di fatture e DDT; non documenta i selettori DOM.
- [Nota Wolters Kluwer MAN-B6FDAR38400, novembre 2018](https://files.supersite.aruba.it/media/29162_852f1c7d880c97f75845d8d40f51cc3d8fd2adb7.pdf), copia pubblica: pagine 3–4 accesso dal servizio; pagina 7 abilitazione degli altri documenti, inclusi DDT; pagina 12 Knowledge Base con tutorial contestuali. Fonte storica, non prova della UI attuale.
- [Indice tutorial Data Group](https://www.data-group.it/software/ipsoa/fattura-smart/tutorial-fattura-smart/): trovati video su anagrafiche, prodotti e documenti. I video non sono stati verificati integralmente e non sono fonte di selettori eseguibili.

## Procedura di lavoro e verifica

1. Accedere a Webdesk con la credenziale autorizzata per l'azienda richiesta.
2. Dalla Home usare Servizi → Fattura SMART. Attendere la pagina effettiva:
   un URL aperto o una pagina bianca non dimostrano l'accesso riuscito.
3. Verificare separatamente azienda emittente e cliente destinatario. L'operatore
   autenticato non identifica necessariamente l'emittente richiesto.
4. Fatture: il riquadro Fatture → Crea nuovo è già stato osservato nella UI.
   Verificare la nuova scheda prima di compilare cliente e righe; attendere e
   selezionare un risultato univoco, poi rileggere quanto inserito.
5. Dichiarazione d'intento: ricercare e verificare quella del cliente corretto.
   Non inventare protocollo/data né considerare sufficiente la scelta dell'IVA.
   La ricerca e associazione automatica completa non sono ancora verificate.
6. DDT: il riquadro D.D.T. → Crea nuovo è stato osservato, ma il modulo e la
   compilazione automatica non sono ancora verificati. Se manca il riquadro,
   controllare la configurazione documenti senza cambiarla automaticamente.
   Consultare il tutorial contestuale prima di implementare i campi di trasporto.
7. Fermarsi prima di salvare (anche bozza), emettere o inviare. Questi divieti
   dell'utente prevalgono sui passaggi di completamento descritti nei manuali.

## Collegamento al codice

`policies/programs.yaml` contiene `operational_guide`, caricato dal modello
`Portal` e restituito da `portal_learn` come `guida_operativa` insieme ai campi
realmente osservati. Non è addestramento del modello né un nuovo esecutore DDT.
La guida non autorizza clic, non installa selettori e non modifica le protezioni.

L'integrazione va distribuita nell'Agent installato prima che sia disponibile
nel programma. Test di caricamento e sola lettura non equivalgono a una prova
reale di fatturazione. Servono ancora verifica emittente, dichiarazione d'intento
e compilazione DDT, senza alcun salvataggio di documenti reali.
