# Kreluna Director sul PC Windows

Non è un sito da telefono. È un’**app per computer Windows**.

**Non serve installare Python.** È già dentro il programma.

Il Director non installa né avvia automaticamente un Agent: funziona anche da solo.
Gli Agent si possono aggiungere in seguito con il pacchetto separato.

## Installazione

1. Scarica `Kreluna-Director-Windows.zip`
2. Estrailo (tasto destro → Estrai tutto)
3. Doppio clic su **Installa.bat**
4. Se Windows blocca: **Altre informazioni** → **Esegui comunque**

L’app va in `%LOCALAPPDATA%\KrelunaDirector` (cartella utente, senza amministratore). Sul desktop compare il collegamento.

## Accesso

- Indirizzo (si apre da sola): `http://127.0.0.1:8080`
- Al primo avvio Kreluna mostra una sola volta email e password personali casuali
- Conservale in un posto sicuro: il pacchetto non contiene password demo

## Aggiornamento (già installata)

Quando compare il pallino rosso sotto **Impostazioni**, premi **Aggiornamento** e poi
**Installa ora**. Kreluna scarica la release ufficiale, verifica l'impronta SHA-256,
sostituisce il programma e si riapre. Database, documenti, configurazione e chiave IA
restano nella cartella dati locale.

Se l'aggiornamento automatico non riesce, usa **Scarica manualmente**, chiudi Kreluna
e avvia `Installa.bat` dal nuovo ZIP.

## Agent su un altro PC dello studio (programma a parte)

Non usare Installa.bat del Director. Usa lo zip **Kreluna-Agenti-Windows**.

1. Sul Director apri **PC & Feature**, scegli il tipo di lavoro e premi **Installa Agent**
2. Premi **Copia collegamento**
3. Sul nuovo PC fai doppio clic su **Installa Kreluna Agent.bat**
4. Incolla il Codice di collegamento quando viene richiesto
5. Se Windows blocca: **Altre informazioni** → **Esegui comunque**

Non occorre modificare file, conoscere l’indirizzo del Director o scegliere di nuovo il
ruolo: il Codice di collegamento contiene già tutto. Sul desktop compare **Kreluna Agent**;
lascialo acceso. Nel Director il pallino del PC diventa verde quando il collegamento è
autenticato.

## Ricreare lo zip

```bash
make windows
```
