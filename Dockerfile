# Dockerfile per il servizio di routing LungoCosta su Render
#
# Strategia: il grafo OTP (graph.obj) è già pre-costruito e incluso nel repo,
# così il container si limita a CARICARLO e servirlo — operazione leggera
# (~450MB di RAM misurati), invece di ricostruirlo da zero (che richiede
# molta più memoria di quella disponibile sul piano free di Render).
#
# Se in futuro serve aggiornare il grafo con un GTFS più recente, va
# ricostruito altrove (es. di nuovo in un sandbox con più RAM, o in locale)
# e il nuovo graph.obj va ricommittato in graph_build/.

FROM eclipse-temurin:21-jre-jammy

WORKDIR /app

# Scarica OpenTripPlanner 2.6.0 (compatibile con Java 21, testato in questa
# conversazione — le versioni 2.7+ richiedono Java 25)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -sL -o otp.jar \
       "https://github.com/opentripplanner/OpenTripPlanner/releases/download/v2.6.0/otp-2.6.0-shaded.jar" \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Il grafo pre-costruito va copiato dal repo (committato in graph_build/)
COPY graph_build/graph.obj /app/graph_build/graph.obj

# Render inietta la porta da usare nella variabile PORT — l'entrypoint la legge
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8080
CMD ["/app/start.sh"]
