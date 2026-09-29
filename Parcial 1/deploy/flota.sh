#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Control de la flota "Granja Zenon - Cacao" en la VM de Azure.
#
#   ./flota.sh instalar   Copia las unidades systemd y las habilita
#   ./flota.sh arrancar   Arranca los 7 nodos que corren en la VM
#   ./flota.sh parar      Para los 7 nodos
#   ./flota.sh estado     Estado resumido de cada nodo
#   ./flota.sh logs       Ultimas lineas del log de cada nodo
#   ./flota.sh seguir X   Sigue en vivo el log del nodo X (ej: dev02)
#   ./flota.sh probar     Prueba de humo: una muestra por nodo y sale
#   ./flota.sh cortar X   Desconexion controlada del nodo X (para la demo)
#   ./flota.sh reconectar X
# ---------------------------------------------------------------------------
set -uo pipefail

BASE="/opt/granjazenon"
NODOS=(dev02 dev04 dev05 dev06 dev07 dev09 dev10)

declare -A SCRIPTS=(
  [dev02]="dev02_lote2_dps_mqtt.py"
  [dev04]="dev04_dosel_websocket.py"
  [dev05]="dev05_estacion_replay_csv.py"
  [dev06]="dev06_meteo_atlas_weather.py"
  [dev07]="dev07_aire_openmeteo.py"
  [dev09]="dev09_riego_http_rest.py"
  [dev10]="dev10_perimetro_paho_mqtt.py"
)

unidad() { echo "granjazenon-$1.service"; }

case "${1:-ayuda}" in

  instalar)
    mkdir -p "${BASE}/logs"
    sudo cp "${BASE}/deploy/systemd/"granjazenon-*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    for n in "${NODOS[@]}"; do sudo systemctl enable "$(unidad "$n")"; done
    echo "Unidades instaladas y habilitadas para el arranque."
    ;;

  arrancar)
    for n in "${NODOS[@]}"; do
      sudo systemctl start "$(unidad "$n")"
      echo "  arrancado  $n"
      sleep 3   # se escalona el arranque para no saturar DPS
    done
    ;;

  parar)
    for n in "${NODOS[@]}"; do
      sudo systemctl stop "$(unidad "$n")"
      echo "  parado     $n"
    done
    ;;

  reiniciar)
    for n in "${NODOS[@]}"; do sudo systemctl restart "$(unidad "$n")"; sleep 2; done
    echo "Flota reiniciada."
    ;;

  estado)
    printf "%-8s %-10s %-10s %s\n" "NODO" "ESTADO" "DESDE" "MENSAJES ENVIADOS"
    printf -- "-%.0s" {1..64}; echo
    for n in "${NODOS[@]}"; do
      estado=$(systemctl is-active "$(unidad "$n")" 2>/dev/null)
      desde=$(systemctl show "$(unidad "$n")" -p ActiveEnterTimestamp --value 2>/dev/null | awk '{print $2}')
      tx=$(grep -c ' TX #' "${BASE}/logs/${n}.log" 2>/dev/null || echo 0)
      printf "%-8s %-10s %-10s %s\n" "$n" "${estado:-?}" "${desde:-—}" "$tx"
    done
    echo
    free -h | head -3
    ;;

  logs)
    for n in "${NODOS[@]}"; do
      echo "===== $n ====="
      tail -n 6 "${BASE}/logs/${n}.log" 2>/dev/null || echo "  (sin log)"
      echo
    done
    ;;

  seguir)
    tail -f "${BASE}/logs/${2:-dev02}.log"
    ;;

  probar)
    for n in "${NODOS[@]}"; do
      echo "===== prueba de humo: $n ====="
      "${BASE}/.venv/bin/python" "${BASE}/${SCRIPTS[$n]}" --una-vez 2>&1 | tail -n 6
      echo
    done
    ;;

  cortar)
    nodo="${2:?indica el nodo, p.ej. ./flota.sh cortar dev02}"
    sudo systemctl stop "$(unidad "$nodo")"
    echo "$(date '+%Y-%m-%d %H:%M:%S')  DESCONEXION CONTROLADA de ${nodo}" \
      | tee -a "${BASE}/logs/desconexiones.log"
    ;;

  reconectar)
    nodo="${2:?indica el nodo, p.ej. ./flota.sh reconectar dev02}"
    sudo systemctl start "$(unidad "$nodo")"
    echo "$(date '+%Y-%m-%d %H:%M:%S')  RECONEXION de ${nodo}" \
      | tee -a "${BASE}/logs/desconexiones.log"
    ;;

  *)
    sed -n '3,20p' "$0"
    ;;
esac
