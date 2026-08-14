# Deploy su Render — v2, con Trenitalia + Trenord combinati

## Cosa è cambiato rispetto al pacchetto precedente

- Il grafo (`graph_build/graph.obj`) ora include **entrambe le reti**:
  Trenitalia (1.925 stazioni) + Trenord (566 stazioni) = 2.491 stazioni
  totali, 5.908 pattern di corsa.
- I cambi tra le due reti sono **automatici**: OpenTripPlanner genera da
  solo i trasferimenti a piedi tra stazioni vicine dei due dataset (es.
  Milano Centrale Trenord ↔ Milano Centrale Trenitalia, ~123 metri di
  distanza) — nessuna configurazione manuale necessaria.
- **`-Xmx` abbassato da 512m a 300m** in `start.sh`: il grafo più grande
  usa più memoria. Misurato sotto carico (10 richieste ripetute su un
  percorso cross-rete): a Xmx300m si stabilizza a ~458MB di RSS reale,
  dentro il limite di 512MB del piano free di Render con margine di
  sicurezza di ~55MB. **Non alzare questo valore senza rimisurare** — a
  Xmx350m si arriva già a ~471MB (margine troppo risicato), a Xmx512m si
  supera il limite del container.

## Limite noto: niente geometria per le tratte Trenord

Il GTFS Trenord non include `shapes.txt` (i tracciati geografici). Per le
tratte Trenord, la mappa (se implementata con `legGeometry`) disegnerà
linee rette tra le stazioni invece del binario reale. Le tratte Trenitalia
restano precise come prima.

## Come aggiornare il servizio già online su Render

1. Nel repository GitHub già collegato a Render, sostituisci:
   - `graph_build/graph.obj` (nuovo file, 26.5MB, incluso in questo pacchetto)
   - `start.sh` (nuova soglia di memoria)
2. Fai commit delle modifiche — Render rileva il push e fa da solo un
   nuovo deploy automatico (se il "auto-deploy" è attivo, comportamento di
   default).
3. Verifica dai log di Render che il servizio riparta senza errori di
   memoria, poi ritesta con una query cross-rete, es.:

```bash
curl -X POST https://TUO-URL.onrender.com/otp/gtfs/v1 \
  -H "Content-Type: application/json" \
  -d '{"query": "{ plan(fromPlace: \"2:S01066\", toPlace: \"1:04501\", date: \"2026-08-13\", time: \"6:00am\", numItineraries: 1) { itineraries { legs { mode from{name} to{name} route{shortName agency{name}} } } } } }"}'
```

(`2:S01066` = Milano Cadorna su Trenord, `1:04501` = Ventimiglia su
Trenitalia — se la risposta mostra un cambio a piedi tra le due reti a
metà del tragitto, il deploy è riuscito.)

## Formato ID stazioni, ora con due prefissi

- `1:CODICE` → stazione Trenitalia (invariato)
- `2:CODICE` → stazione Trenord (nuovo)

L'autocompletamento (query `stops(name: ...)`) restituisce automaticamente
il prefisso giusto per ciascuna stazione trovata — non serve alcuna logica
aggiuntiva lato frontend per distinguere le due reti, sono già unificate
nello stesso indice di ricerca.
