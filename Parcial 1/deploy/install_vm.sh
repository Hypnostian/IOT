#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Preparacion de la VM de Azure "granjazenon" para la flota IoT del Parcial 1.
#
#   Host  : <nombre-dns-de-la-VM> (<IP-de-la-VM>)
#   SO    : Ubuntu 24.04.4 LTS
#   Tamano: 2 vCPU / 892 MiB RAM  -> por eso se crea swap
#
# Uso (desde el portatil):
#   scp -i granjazenon_key.pem deploy/install_vm.sh zenon@<IP-de-la-VM>:~/
#   ssh -i granjazenon_key.pem zenon@<IP-de-la-VM> 'bash ~/install_vm.sh'
#
# Es idempotente: se puede volver a ejecutar sin romper nada.
# ---------------------------------------------------------------------------
set -euo pipefail

BASE="/opt/granjazenon"
USUARIO="zenon"

echo "=============================================================="
echo " 1/6  Actualizacion del sistema"
echo "=============================================================="
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get -o Dpkg::Options::="--force-confdef" \
             -o Dpkg::Options::="--force-confold" upgrade -y
sudo apt-get autoremove -y

echo
echo "=============================================================="
echo " 2/6  Paquetes necesarios"
echo "=============================================================="
sudo apt-get install -y \
    python3-venv python3-pip python3-dev \
    build-essential ca-certificates curl jq git tmux \
    chrony tzdata

# El reloj tiene que estar fino: los tokens SAS caducan y DPS rechaza
# dispositivos con deriva horaria.
sudo systemctl enable --now chrony
sudo timedatectl set-timezone America/Bogota || true

echo
echo "=============================================================="
echo " 3/6  Memoria de intercambio (swap)"
echo "=============================================================="
# La VM tiene menos de 1 GiB y va a sostener 6 procesos Python a la vez.
if ! sudo swapon --show | grep -q swapfile; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    fi
    # Con poca RAM conviene que el kernel use swap antes de matar procesos.
    echo 'vm.swappiness=20' | sudo tee /etc/sysctl.d/99-granjazenon.conf >/dev/null
    sudo sysctl -p /etc/sysctl.d/99-granjazenon.conf >/dev/null
    echo "Swap de 2 GiB creada."
else
    echo "Ya existe swap, no se toca."
fi

echo
echo "=============================================================="
echo " 4/6  Entorno de la aplicacion en ${BASE}"
echo "=============================================================="
sudo mkdir -p "${BASE}"
sudo chown -R "${USUARIO}:${USUARIO}" "${BASE}"

if [ ! -d "${BASE}/.venv" ]; then
    python3 -m venv "${BASE}/.venv"
    echo "Entorno virtual creado."
fi
"${BASE}/.venv/bin/pip" install --upgrade pip wheel --quiet

if [ -f "${BASE}/requirements.txt" ]; then
    echo "Instalando dependencias de Python (puede tardar unos minutos)..."
    "${BASE}/.venv/bin/pip" install -r "${BASE}/requirements.txt" --quiet
    echo "Dependencias instaladas."
else
    echo "AVISO: todavia no se ha subido requirements.txt a ${BASE}."
fi

echo
echo "=============================================================="
echo " 5/6  Comprobacion de salida a Azure"
echo "=============================================================="
for destino in global.azure-devices-provisioning.net:8883 \
               atlas.microsoft.com:443 \
               air-quality-api.open-meteo.com:443; do
    host="${destino%%:*}"; puerto="${destino##*:}"
    if timeout 6 bash -c "</dev/tcp/${host}/${puerto}" 2>/dev/null; then
        echo "  OK      ${destino}"
    else
        echo "  BLOQUEADO ${destino}"
    fi
done

echo
echo "=============================================================="
echo " 6/6  Resumen"
echo "=============================================================="
echo "Python : $(python3 --version)"
echo "Venv   : ${BASE}/.venv"
free -h | head -3
df -h / | tail -1
echo
echo "VM lista. Siguiente paso: subir el codigo y activar los servicios."
