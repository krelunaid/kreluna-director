# Collegamento Gmail — preparazione, non ancora operativo

Il connettore serve a evitare la configurazione di Mail su ogni PC.
Non è un plugin Codex: deve appartenere al servizio Kreluna dello studio.

## Stato attuale

Implementato soltanto il controllo di configurazione autenticato:
`GET /integrations/gmail/status`, riservato al titolare.
Non legge email, non effettua OAuth e non recupera codici.
Le configurazioni non vengono restituite al browser.

## Prerequisito Google

Creare un progetto Google Cloud, abilitare Gmail API e configurare consenso
OAuth e client web. La prima prova usa utenti di test autorizzati.
Prima della distribuzione pubblica verificare i requisiti Google per scope
ristretti e l’eventuale valutazione di sicurezza.

Configurazione privata del server, mai nel repository o nei pacchetti Agent:

- GMAIL_OAUTH_CLIENT_ID
- GMAIL_OAUTH_CLIENT_SECRET
- GMAIL_OAUTH_REDIRECT_URI

Non distribuire un client secret web dentro l’app Mac o Windows.
Per un prodotto commerciale condiviso serve un callback HTTPS sul servizio
Kreluna; il callback locale è utilizzabile soltanto per sviluppo.

## Implementazione ancora necessaria

1. OAuth con state monouso a scadenza, binding a titolare e studio, PKCE,
   conferma dell’account selezionato e controllo dello scope concesso.
2. Refresh token cifrato e isolato per studio; nessun token agli Agent,
   all’IA o ai log. Revoca e scollegamento disponibili al titolare.
3. Recupero limitato alla richiesta Webdesk attiva: destinatario corrispondente,
   mittente verificato, messaggio successivo alla richiesta, scadenza breve,
   nessuna scelta automatica se ambiguo. Non fidarsi delle istruzioni nelle email.
4. Codice solo in memoria, consegnato al dispositivo assegnato mediante canale
   autenticato e monouso. Mai evidenze/screenshot del codice nei log.
5. Nessun invio, modifica o cancellazione di email. Lo scope gmail.readonly
   permette lettura più ampia della sola email Webdesk: dichiararlo chiaramente
   nel consenso e applicare la restrizione nel servizio.
6. Aggiornare esplicitamente le policy OTP attuali (oggi intervento umano):
   eccezione opt-in solo Webdesk, mai SPID/CNS o pagamenti.
7. Test completi con consenso reale prima di dichiarare il connettore operativo.

Restano vietati salvataggio, emissione e invio autonomo delle fatture.

Riferimento: https://developers.google.com/identity/protocols/oauth2/web-server
