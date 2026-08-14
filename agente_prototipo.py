"""
Prototipo: agente cercatore di percorsi per LungoCosta
=========================================================

Pipeline: richiesta in linguaggio naturale -> parametri strutturati (via Claude,
con fallback a un parser semplice se manca la API key) -> query a OpenTripPlanner
(motore di routing sul GTFS Trenitalia) -> risposta narrativa in italiano.

Per usarlo con Claude vero:
    export ANTHROPIC_API_KEY="la-tua-chiave"
    python3 agente_prototipo.py

Senza chiave, usa un parser di riserva (regole semplici) solo per la demo:
la pipeline OTP -> formattazione funziona comunque allo stesso modo.

Richiede un server OpenTripPlanner attivo (vedi avvio_server.sh) sulla porta 8080,
caricato con il GTFS Trenitalia.
"""

import os
import re
import csv
import json
import urllib.request

# Dopo il deploy su Render, sostituisci con l'URL pubblico assegnato
# (es. "https://lungocosta-routing.onrender.com/otp/gtfs/v1"), oppure leggilo
# da una variabile d'ambiente: OTP_URL = os.environ.get("OTP_URL", "http://localhost:8080/otp/gtfs/v1")
OTP_URL = os.environ.get("OTP_URL", "http://localhost:8080/otp/gtfs/v1")
STOPS_FILE = os.environ.get("STOPS_FILE", "/home/claude/gtfs/stops.txt")  # per la ricerca nome -> id stazione


# ---------------------------------------------------------------------------
# 1. Indice stazioni (nome -> gtfsId nel formato che OTP si aspetta)
# ---------------------------------------------------------------------------

def carica_stazioni():
    """Carica stops.txt e costruisce un indice nome (maiuscolo) -> gtfsId OTP."""
    indice = {}
    with open(STOPS_FILE, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            nome = row["stop_name"].strip().upper()
            gtfs_id = f"1:{row['stop_id']}"  # OTP antepone l'indice feed "1:"
            indice[nome] = gtfs_id
    return indice


def trova_stazione(indice, testo_libero):
    """Trova la stazione più vicina al nome fornito (match esatto o per contenimento)."""
    testo = testo_libero.strip().upper()
    if not testo:
        return None, None
    if testo in indice:
        return testo, indice[testo]
    # match parziale: la stazione contiene il testo cercato, o viceversa
    candidati = [n for n in indice if testo in n or n in testo]
    if candidati:
        # preferisci il nome più corto (di solito la stazione principale, es. "PISA CENTRALE")
        migliore = min(candidati, key=len)
        return migliore, indice[migliore]
    return None, None


# ---------------------------------------------------------------------------
# 2. Interpretazione della richiesta (Claude, con fallback)
# ---------------------------------------------------------------------------

SCHEMA_RICHIESTA = {
    "name": "estrai_richiesta_viaggio",
    "description": "Estrae i parametri strutturati di una ricerca di viaggio in treno",
    "input_schema": {
        "type": "object",
        "properties": {
            "origine": {"type": "string", "description": "Stazione di partenza"},
            "destinazione": {"type": "string", "description": "Stazione di arrivo"},
            "data": {"type": "string", "description": "Data nel formato YYYY-MM-DD"},
            "ora": {"type": "string", "description": "Ora di partenza preferita, formato HH:MMam/pm"},
            "evita_intercity": {"type": "boolean", "description": "true se l'utente preferisce solo regionali"},
        },
        "required": ["origine", "destinazione"],
    },
}


def interpreta_con_claude(testo, data_default):
    """Chiama Claude con tool-use per estrarre i parametri dalla richiesta libera."""
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        tools=[SCHEMA_RICHIESTA],
        tool_choice={"type": "tool", "name": "estrai_richiesta_viaggio"},
        messages=[{
            "role": "user",
            "content": (
                f"Data di oggi: {data_default}. Richiesta dell'utente: \"{testo}\". "
                "Estrai i parametri del viaggio. Se la data non è specificata usa oggi. "
                "Se l'ora non è specificata usa le 07:00am."
            ),
        }],
    )
    for block in msg.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Claude non ha restituito un tool_use")


def interpreta_con_fallback(testo, data_default):
    """Parser di riserva a regole semplici, usato solo se manca ANTHROPIC_API_KEY.
    Serve a far girare la demo end-to-end senza chiave — NON è il pezzo da tenere
    in produzione, quello è interpreta_con_claude."""
    indice = carica_stazioni()
    nomi_stazioni = sorted(indice.keys(), key=len, reverse=True)

    testo_upper = testo.upper()
    parole_testo = re.findall(r"[A-ZÀ-Ù.]+", testo_upper)
    parole_testo_set = set(parole_testo)

    # match: nome stazione intero contenuto nel testo, oppure prima parola del
    # nome stazione presente come parola isolata (es. "CAMOGLI" trova "CAMOGLI
    # S.FRUTTUOSO") — richiede almeno 5 caratteri per ridurre ambiguità tra
    # stazioni con lo stesso primo termine (es. le tante "REGGIO DI CALABRIA ...")
    candidati = [
        n for n in nomi_stazioni
        if n in testo_upper or (len(n.split()[0]) >= 5 and n.split()[0] in parole_testo_set)
    ]
    # rimuove sovrapposizioni (es. "ROMA" dentro "ROMA TERMINI")
    candidati_puliti = [n for n in candidati if not any(n != m and n in m for m in candidati)]

    # tra stazioni con lo stesso primo termine, preferisci quella il cui nome
    # per intero è più vicino al testo (più parole del nome trovate nel testo)
    def punteggio(nome_stazione):
        parole_nome = nome_stazione.split()
        return sum(1 for p in parole_nome if p in parole_testo_set)

    # posizione di prima menzione nel testo, per mantenere l'ordine origine/destinazione
    def posizione(nome_stazione):
        prima_parola = nome_stazione.split()[0]
        idx = testo_upper.find(nome_stazione)
        if idx == -1:
            idx = testo_upper.find(prima_parola)
        return idx

    raggruppate = {}
    for n in candidati_puliti:
        chiave = n.split()[0]
        if chiave not in raggruppate or punteggio(n) > punteggio(raggruppate[chiave]):
            raggruppate[chiave] = n

    trovate_pulite = sorted(raggruppate.values(), key=posizione)[:2]

    origine = trovate_pulite[0] if len(trovate_pulite) >= 1 else None
    destinazione = trovate_pulite[1] if len(trovate_pulite) >= 2 else None

    ora_match = re.search(r"(\d{1,2})[:.](\d{2})", testo)
    ora = f"{ora_match.group(1)}:{ora_match.group(2)}am" if ora_match else "7:00am"

    evita_ic = bool(re.search(r"\bregional|solo reg|niente intercity|senza IC\b", testo, re.I))

    return {
        "origine": origine or "",
        "destinazione": destinazione or "",
        "data": data_default,
        "ora": ora,
        "evita_intercity": evita_ic,
    }


def interpreta_richiesta(testo, data_default="2026-08-13"):
    if os.environ.get("ANTHROPIC_API_KEY"):
        return interpreta_con_claude(testo, data_default)
    print("[nota] ANTHROPIC_API_KEY non impostata: uso il parser di riserva per la demo.\n")
    return interpreta_con_fallback(testo, data_default)


# ---------------------------------------------------------------------------
# 3. Query a OpenTripPlanner
# ---------------------------------------------------------------------------

def query_otp(origine_id, destinazione_id, data, ora, num_itinerari=5):
    query = f"""
    {{
      plan(fromPlace: "{origine_id}", toPlace: "{destinazione_id}",
           date: "{data}", time: "{ora}", numItineraries: {num_itinerari}) {{
        itineraries {{
          startTime
          endTime
          legs {{
            mode
            startTime
            endTime
            from {{ name }}
            to {{ name }}
            route {{ shortName }}
            trip {{ tripShortName }}
          }}
        }}
      }}
    }}
    """
    payload = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        OTP_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        risultato = json.loads(resp.read())
    return risultato.get("data", {}).get("plan", {}).get("itineraries", [])


# ---------------------------------------------------------------------------
# 4. Filtro (es. "evita Intercity") e formattazione narrativa
# ---------------------------------------------------------------------------

def filtra_itinerari(itinerari, evita_intercity):
    if not evita_intercity:
        return itinerari
    filtrati = [
        it for it in itinerari
        if all(leg["route"]["shortName"] not in ("IC", "ICN", "FR", "FB", "FA", "EC")
               for leg in it["legs"])
    ]
    return filtrati or itinerari  # se il filtro svuota tutto, meglio mostrare comunque qualcosa


def ms_a_orario(ms):
    import datetime
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%H:%M")


def formatta_risposta(itinerari, origine_nome, destinazione_nome):
    if not itinerari:
        return f"Non ho trovato collegamenti reali tra {origine_nome} e {destinazione_nome} per questi parametri."

    righe = [f"Ecco i collegamenti trovati da {origine_nome} a {destinazione_nome}:\n"]
    for i, it in enumerate(itinerari[:3], 1):
        partenza = ms_a_orario(it["startTime"])
        arrivo = ms_a_orario(it["endTime"])
        n_cambi = len(it["legs"]) - 1
        righe.append(f"Opzione {i}: {partenza} -> {arrivo} ({n_cambi} cambio/i)")
        for leg in it["legs"]:
            tipo = leg["route"]["shortName"]
            numero = leg["trip"]["tripShortName"]
            da = leg["from"]["name"]
            a = leg["to"]["name"]
            h1 = ms_a_orario(leg["startTime"])
            h2 = ms_a_orario(leg["endTime"])
            righe.append(f"   {tipo} {numero}: {da} {h1} -> {a} {h2}")
        righe.append("")
    return "\n".join(righe)


# ---------------------------------------------------------------------------
# 5. Pipeline completa
# ---------------------------------------------------------------------------

def cerca_percorso(richiesta_testuale, data_default="2026-08-13"):
    parametri = interpreta_richiesta(richiesta_testuale, data_default)
    print("Parametri interpretati:", parametri, "\n")

    indice_stazioni = carica_stazioni()
    nome_origine, id_origine = trova_stazione(indice_stazioni, parametri["origine"])
    nome_dest, id_dest = trova_stazione(indice_stazioni, parametri["destinazione"])

    if not id_origine or not id_dest:
        return f"Non ho riconosciuto una o entrambe le stazioni: '{parametri['origine']}' / '{parametri['destinazione']}'."

    itinerari = query_otp(id_origine, id_dest, parametri["data"], parametri["ora"])
    itinerari = filtra_itinerari(itinerari, parametri.get("evita_intercity", False))

    return formatta_risposta(itinerari, nome_origine, nome_dest)


if __name__ == "__main__":
    richiesta = "Vorrei andare da Ventimiglia a Camogli domani mattina, meglio se regionale"
    print(f"Richiesta: \"{richiesta}\"\n")
    print(cerca_percorso(richiesta))
