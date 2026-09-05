# Assistenza remota: prima implementazione macOS

In Director, **Vedi Agent → scegli PC → Apri schermo remoto**.
L’Agent deve essere inattivo: non viene cancellato o rimesso in coda alcun lavoro.
La sessione riserva il PC e impedisce l’esecuzione delle automazioni.
**Intervieni** abilita clic, testo Unicode e tasti limitati. Invio richiede conferma.
**Chiudi e libera il PC** termina il controllo, senza riavviare lavori interrotti.

## Limiti espliciti

- Solo macOS e schermo principale; immagini JPEG aggiornate ogni circa 2 secondi,
  non streaming video. Niente trascinamento, monitor secondari o Windows per ora.
- Necessari i permessi macOS Registrazione schermo e Accessibilità per Kreluna Agent.
- Nessuna ripresa automatica dal checkpoint del lavoro: ancora da implementare.
- La prova su due PC distinti e i comandi di input reali sono ancora da verificare.
  Nella prima prova installata, macOS ha negato Registrazione schermo.

## Protezioni

- API autenticata, ruolo titolare/approvatore, licenza attiva e isolamento dello studio.
- Risposte legate al dispositivo e alla specifica WebSocket autenticata.
- Sessione casuale legata all’utente, scadenza dopo 30 secondi senza richieste.
- Nessuna modifica al controllo di pausa preesistente; nessun replay automatico.
- Vietato acquisire il controllo se ci sono task o thread di automazione ancora attivi.
- Input solo dopo Intervieni, su frame di massimo 5 secondi, monouso per ogni comando.
- Nessuna immagine o testo digitato salvati nel database, nell’audit o nelle prove dei task.
  La cattura macOS usa un file temporaneo eliminato dopo la conversione in JPEG.
- La condivisione mostra anche informazioni sensibili eventualmente presenti sullo schermo:
  avvio esplicito con avvertenza nell’interfaccia. Su rete usare il collegamento TLS degli Agent.

## Verifica

`pytest tests/unit/test_remote_control.py` controlla esclusione dei worker,
scadenza, proprietario, frame monouso, rilascio dopo errore e risposta da socket corretto.
La pagina locale `tests/fixtures/remote-control.html` serve a verificare mouse e tastiera
senza usare un gestionale o inviare documenti.
