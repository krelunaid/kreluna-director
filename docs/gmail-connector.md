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
di Google. verify effettua il controllo reale. available richiede anche
l’autorizzazione esplicita del titolare ai codici Webdesk, disattivata di default.
PUT /integrations/gmail/webdesk-policy abilita o disabilita questa eccezione.

## Validazione Webdesk

Il percorso Mac riconosce esclusivamente la pagina HTTPS
www.webdesk.it/Account/AccessNewLocation.aspx (anche senza www): richiesta del
codice, campo MainContent_CodSicurezza, pulsante Procedi, conferma postazione,
link Accedi a webdesk. Non seleziona automaticamente la fiducia per 90 giorni.
Il successo richiede poi la dashboard, non la sola scomparsa della password.

L’Agent assegnato firma start/poll su /agent/webdesk-code. Il Director verifica
task attivo, studio, dispositivo, Fort Knox richiesto, portale fatture-webdesk,
opt-in e destinatario uguale all’account Gmail. Una sola richiesta per task,
una per studio alla volta, scadenza tre minuti, polling limitato e monouso.
Il messaggio deve essere successivo alla richiesta, non spam/cestino, provenire
da noreply@webdesk.it con DMARC positivo del ricevente Gmail, contenere il login
atteso e un unico codice nel formato osservato. Account errato, ambiguità,
revoca, cancellazione o cambio dispositivo fermano il percorso. I codici
rimangono in memoria e viaggiano solo al dispositivo autorizzato sul canale
protetto (loopback ammesso sul Mac); non sono scritti nei log o nelle evidenze.

scripts/check-webdesk-gmail-local.py prova il login reale con task e dispositivo
effimeri in memoria e copie cifrate delle credenziali. Non modifica la coda
installata, non crea fatture e non salva screenshot. Il 4 settembre 2026 la
prova ha raggiunto la conferma di validazione reale; il link finale, aggiunto
dopo averne osservato il formato, ha aperto la dashboard Webdesk. Non equivale
ancora alla verifica end-to-end di una fattura né all’installazione dell’Agent.

## Limiti e lavoro residuo

Il primo consenso Google resta necessario. In modalità Test i refresh token
con scope Gmail possono scadere dopo 7 giorni: non promettere accesso permanente.
Per la distribuzione pubblica completare la verifica degli scope ristretti.
Un servizio centralizzato richiede client web e callback HTTPS; non distribuire
client secret web nei pacchetti desktop.

gmail.readonly permette la lettura dell’intera casella. Il collegamento usa
token, revoca e profilo. La validazione legge solo messaggi selezionati dalla
ricerca Webdesk e con metadati verificati: nessun invio, modifica o cancellazione.

L’eccezione opt-in riguarda solo la validazione postazione Webdesk.
Gli altri OTP, SPID/CNS e pagamenti restano esclusi.

Restano vietati salvataggio, emissione e invio autonomo delle fatture.

Riferimenti:
https://developers.google.com/identity/protocols/oauth2/native-app
https://developers.google.com/identity/protocols/oauth2#expiration
