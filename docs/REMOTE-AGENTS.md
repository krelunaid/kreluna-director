# Collegamento remoto Director–Agent

Kreluna Director conserva database, Fort Knox e dashboard sul computer dello studio. Per
raggiungere gli Agent su altri computer usa un Cloudflare Tunnel con hostname stabile. Il
connettore apre soltanto connessioni in uscita: non richiede porte aperte sul router.

```text
Director locale (127.0.0.1:8080)
        │ cloudflared, uscita cifrata
        ▼
hostname HTTPS dello studio
        ▲
        │ HTTPS / WSS
Kreluna Agent Mac o Windows
```

## Preparazione una tantum

1. Creare un tunnel gestito dalla dashboard Cloudflare.
2. Assegnare un hostname HTTPS specifico per lo studio.
3. Configurare l’ingresso del tunnel verso `http://127.0.0.1:8080`.
4. In Director aprire **Impostazioni → PC remoti → Configura collegamento**.
5. Inserire hostname e token del tunnel. Il token viene scritto in un file separato con
   permessi locali e non viene restituito dalle API.
6. Premere **Verifica**. Lo stato verde richiede che l’hostname raggiunga questo stesso
   Director e che la chiave pubblica del server corrisponda.

Il pacchetto installabile include una versione bloccata di `cloudflared`, verificata tramite
SHA-256 durante la build. In produzione il connettore usa `--no-autoupdate`: viene aggiornato
insieme a Kreluna, non autonomamente.

## Collegare un PC

1. In **PC & Feature** premere **Installa Agent** sul ruolo desiderato.
2. Director mostra un solo **Codice di collegamento** e permette di copiarlo soltanto
   quando il collegamento remoto è verificato.
3. Sul PC aprire Kreluna Agent e incollare una volta il Codice di collegamento.
4. L’Agent genera localmente una chiave Ed25519 e riscatta il codice una sola volta.
5. La WebSocket richiede una challenge firmata prima di segnare il PC come online.

Il Codice di collegamento contiene già indirizzo HTTPS, ruolo del PC e codice di
attivazione. È monouso, scade e va trattato come una password temporanea: non deve essere
pubblicato o inoltrato a persone diverse da chi installa quel PC.

Il pallino diventa verde soltanto quando la WebSocket autenticata è nel registry del tenant e
i battiti del PC sono recenti. Un interruttore acceso senza connessione non è “online”.

## Superficie pubblica ridotta

L’hostname remoto accetta esclusivamente:

- health check senza segreti;
- enrollment monouso;
- WebSocket Agent con challenge Ed25519;
- risultati e richieste Agent firmati e legati a tenant, device e task.

Dashboard, login, impostazioni, documenti, API amministrative e interfaccia Fort Knox vengono
rifiutati sull’hostname remoto. Restano utilizzabili soltanto dalla finestra locale del
Director.

## Barriere invariabili

- nessuna shell remota e nessun `eval`;
- nessun invio reale di fatture, F24, PEC o pagamenti;
- niente login automatico SPID, CNS, CIE, smart card o OTP;
- le schermate non vengono inviate al modello;
- le credenziali Fort Knox sono consegnate una sola volta al device assegnato, tramite HTTPS,
  e non transitano nell’IA.

Per SPID o OTP l’Agent deve fermarsi davanti alla schermata e attendere l’intervento della
persona. Un eventuale programma di assistenza remota umana rimane separato da Kreluna Agent.

Riferimenti operativi: [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/),
[tunnel gestiti da dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).
