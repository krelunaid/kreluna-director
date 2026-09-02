# IA Kreluna: gateway gestito

Il gateway consente di vendere Kreluna Director con Grok già disponibile senza
distribuire la chiave xAI ai clienti. La chiave upstream resta un segreto del
Worker Cloudflare; ogni installazione riceve soltanto un token di licenza
Kreluna distinto e revocabile.

## Confine di sicurezza

- Il Director invia al gateway soltanto messaggi testuali destinati al planner.
- Immagini, schermate, strumenti, function calling e streaming sono rifiutati.
- Il gateway non salva prompt, risposte o credenziali dei clienti.
- Il database registra soltanto licenza, contatori, modello, esito, latenza e
  costo restituito da xAI.
- Il modello è fissato a `grok-4.6`; il cliente non può sostituirlo via richiesta.
- Quote giornaliere, quote mensili e limite per minuto sono applicati per licenza.
- La revoca blocca immediatamente le successive richieste della licenza.
- Le policy del Director restano l'autorità: niente shell remota o `eval`, niente
  invii F24/PEC/pagamenti, niente login automatico SPID/CNS e niente schermate al
  modello.

## Componenti

- Worker: `apps/kreluna-ai-gateway/src`
- Database D1 e migrazioni: `apps/kreluna-ai-gateway/migrations`
- Configurazione Cloudflare: `apps/kreluna-ai-gateway/wrangler.jsonc`
- Token locale Mac: `~/Library/Application Support/KrelunaDirector/managed_ai.token`
- Token locale Windows: `%LOCALAPPDATA%\KrelunaDirector\managed_ai.token`

Il token locale non è una chiave xAI. È limitato, può essere revocato e viene
salvato con permessi locali restrittivi. Gli aggiornamenti dell'app conservano
la cartella dati, quindi conservano anche la licenza.

## Segreti di produzione

Configurare esclusivamente come secret Cloudflare:

- `XAI_API_KEY`: chiave xAI dedicata al gateway.
- `ADMIN_TOKEN`: credenziale lunga e casuale per creare o revocare licenze.

Non inserire questi valori nel repository, nell'app, nelle release o nei log.
La credenziale amministrativa operativa può essere custodita nel Portachiavi
del Mac del gestore.

## Flusso di vendita

1. Creare una licenza con identificativo cliente, piano e quote.
2. Consegnare il token restituito una sola volta all'installazione del cliente.
3. Salvare il token come `managed_ai.token` nella cartella Kreluna del cliente.
4. Il cliente apre **Impostazioni → IA Kreluna**, incolla il codice e preme
   **Attiva IA**. L'app lo verifica online e lo conserva fuori dal programma
   con permessi locali privati.
5. In caso di cessazione o compromissione, revocare la singola licenza senza
   ruotare la chiave xAI e senza interferire con gli altri clienti.

Non usare una licenza comune in tutti gli installer e non esporre mai
l'endpoint amministrativo al client. Il codice cliente accede soltanto agli
endpoint IA e può essere revocato senza cambiare gli installer.

Il venditore può creare, controllare e revocare le licenze con
`scripts/cloudflare/customer-license.py`. Lo script legge la credenziale
amministrativa da `KRELUNA_GATEWAY_ADMIN_TOKEN` oppure la chiede senza mostrarla:

```bash
python3 scripts/cloudflare/customer-license.py create studio-rossi "Studio Rossi"
python3 scripts/cloudflare/customer-license.py status ID_LICENZA
python3 scripts/cloudflare/customer-license.py revoke ID_LICENZA
```

Conservare l'ID licenza nella scheda commerciale del cliente. Il codice di
attivazione viene restituito una sola volta e va consegnato con un canale
riservato.

## Verifiche prima della pubblicazione

Da `apps/kreluna-ai-gateway` eseguire `pnpm run check`. Il controllo comprende
tipi, test nel runtime Workers e build a secco. La CI principale esegue inoltre
lint, test e build del Director.

Prima del deploy applicare le migrazioni D1, configurare entrambi i secret e
verificare `/health`, `/v1/models`, una richiesta testuale e la revoca di una
licenza di prova. Una risposta non configurata o un errore xAI deve restare
esplicito: non è consentito un fallback silenzioso a OpenAI, Ollama o altro.
