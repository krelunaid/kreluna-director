# Kreluna Fort Knox

Fort Knox custodisce gli accessi dei clienti ai portali professionali. Il titolare
dello studio può inserire un accesso dal programma o importare più clienti con un
CSV. Ogni accesso include il link HTTPS del portale, così l'Agent sa quale indirizzo
aprire senza chiederlo all'IA. Il segreto non viene mai restituito dalla API e non
esiste un'esportazione.

## Flusso

1. Il titolare autenticato inserisce cliente, portale, link, username e password/token.
2. Il Director rifiuta SPID, CNS, CIE, smart card e OTP.
3. Il server deriva una chiave distinta per lo studio dalla chiave master e cifra
   username e segreto con AES-GCM e contesto autenticato.
4. Il database conserva solo i ciphertext; interfaccia e audit usano dati
   mascherati o identificatori tecnici.
5. Un Agent assegnato può ricevere l'accesso una sola volta, per uno specifico task,
   soltanto su HTTPS o sullo stesso computer. Compila i campi ma non preme Accedi.

## Requisiti per il server centrale

- `DIRECTOR_ENV=production` e avvio fail-closed.
- `DIRECTOR_PUBLIC_URL` esclusivamente HTTPS.
- `DIRECTOR_CREDENTIAL_KEY` casuale, distinta dagli altri segreti e custodita nel
  secret manager dell'infrastruttura, non nel repository o nel database.
- Database non esposto a Internet, backup cifrati, accesso amministrativo limitato
  e rotazione documentata della chiave master.
- Un tenant per studio, ruoli minimi e audit monitorato.

Il pacchetto desktop può usare Fort Knox localmente. Per offrire la custodia
centralizzata ai clienti occorre distribuire lo stesso Director API su
un'infrastruttura HTTPS conforme a questi requisiti; il codice non trasforma una
macchina locale in un servizio sicuro semplicemente rendendone pubblica la porta.

## Barriere permanenti

- niente shell remota o `eval`;
- niente invio reale di fatture, F24, PEC o pagamenti;
- niente login automatico con SPID, CNS o CIE;
- niente OTP conservati;
- niente schermate o credenziali inviate al modello IA.
