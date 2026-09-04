# Collegamento Gmail — OAuth locale

Implementati autorizzazione del titolare, PKCE S256, state casuale monouso con
scadenza di 5 minuti, verifica dell’indirizzo scelto, refresh token cifrato con
contesto dello studio, rinnovo senza nuovo consenso e scollegamento/revoca.
La dashboard espone Gmail in Impostazioni. Nessun token al browser, agli Agent
o all’IA. Il callback non conserva code/state nei log di accesso.

## Prova sul Mac

Google Cloud: progetto dedicato, Gmail API abilitata, consenso esterno in Test,
account aggiunto come utente di prova, client Applicazione desktop.
Conservare il JSON scaricato da Google come gmail-oauth-client.json nella
directory privata Application Support/KrelunaDirector, con permessi 0600.
Non includere questo file, password o token nel repository o nello zip.
Il launcher rileva il file; il ritorno OAuth usa il Director locale.

La prova isolata scripts/check-gmail-local.py --email ACCOUNT apre Safari,
attende il callback su una porta libera e verifica un rinnovo del token.
Usa il database e la chiave dell’installazione esistente, richiede un solo
titolare e non avvia code, Agent o operazioni sulle fatture.

Il 4 settembre 2026 è riuscita una prova reale locale di autorizzazione e
rinnovo. Questo NON verifica fatture automatiche o recupero di codici Webdesk.

## API riservate al titolare

- GET /integrations/gmail/status: configurazione e collegamento memorizzato.
- POST /integrations/gmail/connect: email attesa e consenso informativo;
  restituisce solo l’URL Google. Modalità desktop limitata a client locali.
- GET /integrations/gmail/callback: state monouso, HTML senza segreti.
- POST /integrations/gmail/verify: rinnovo e verifica identità via Google.
- DELETE /integrations/gmail/connection: elimina dati locali e tenta revoca
  Google; in caso di fallimento invita a revocare dal proprio account.

connected indica un collegamento memorizzato, non la raggiungibilità attuale
di Google. verify effettua il controllo reale. available resta falso:
il recupero automatico dei codici Webdesk non è ancora implementato.

## Limiti e lavoro residuo

Il primo consenso Google resta necessario. In modalità Test i refresh token
con scope Gmail possono scadere dopo 7 giorni: non promettere accesso permanente.
Per la distribuzione pubblica completare la verifica degli scope ristretti.
Un servizio centralizzato richiede client web e callback HTTPS; non distribuire
client secret web nei pacchetti desktop.

gmail.readonly permette la lettura dell’intera casella. Attualmente sono
chiamati solo token, revoca e profilo Gmail: nessun corpo email letto,
inviato, modificato o cancellato.

Prima di automatizzare i codici serve un’eccezione opt-in alla policy OTP
limitata a Webdesk: mittente/destinatario verificati, richiesta attiva,
finestra temporale breve, blocco su ambiguità e consegna monouso al solo Agent
assegnato. Mai SPID/CNS o pagamenti; nessun codice nei log o evidenze.

Restano vietati salvataggio, emissione e invio autonomo delle fatture.

Riferimenti:
https://developers.google.com/identity/protocols/oauth2/native-app
https://developers.google.com/identity/protocols/oauth2#expiration
