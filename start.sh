#!/bin/sh
# Render fornisce la porta da usare nella variabile d'ambiente PORT.
# Il piano free ha 512MB di RAM totali. Con il grafo combinato
# Trenitalia+Trenord, misurato sotto carico: -Xmx300m -> ~458MB di RSS
# reale (margine ~55MB). NON alzare senza rimisurare: con -Xmx350m si
# arriva a ~471MB, con -Xmx512m si supera il limite del container (~538MB,
# rischio OOM-kill).
PORT="${PORT:-8080}"
exec java -Xmx300m -jar /app/otp.jar --load --serve /app/graph_build --port "$PORT"
