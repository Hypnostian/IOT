# Granja Zenón — Cacao

**Parcial 1 · IoT + Cloud y Sistemas Distribuidos · UNAB 2026-II**
Escenario **5.3 — Granja y cultivo de cacao** sobre Azure IoT Central.

Flota de **10 dispositivos**, cada uno con un **origen de envío distinto**, que
monitorea un predio cacaotero de 11,4 ha en la vereda La Colorada, San Vicente
de Chucurí (Santander).

- **Integrantes:** Juan Sebastián Lizcano Jaimes · Angie Katherine Suárez Ortiz · Miguel Ángel Hernández Quintero
- **Documento del proyecto:** [`docs/Proyecto_GranjaZenon_Cacao.pdf`](docs/Proyecto_GranjaZenon_Cacao.pdf) (versión editable en [`.docx`](docs/Proyecto_GranjaZenon_Cacao.docx))
- **Arquitectura de referencia:** [`docs/img/arquitectura_referencia_flota.png`](docs/img/arquitectura_referencia_flota.png)

---

## La flota

| # | Dispositivo | Zona | Origen de envío | Protocolo | Intervalo | Dónde corre |
|---|---|---|---|---|---|---|
| 01 | `gz-01-lote1-wokwi` | Lote de cultivo 1 | Wokwi ESP32 #1 | MQTT 8883 | 15 s | Portátil (Wokwi) |
| 02 | `gz-02-lote2-python` | Lote de cultivo 2 | Python `azure-iot-device` | MQTT 8883 | 15 s | VM Azure |
| 03 | `gz-03-lote3-twin` | Lote de cultivo 3 | Digital Twin nativo de IoT Central | interno | ≈ 75 s | IoT Central |
| 04 | `gz-04-dosel-ws` | Dosel y sombrío | Python con MQTT sobre WebSocket | WSS 443 | 60 s | VM Azure |
| 05 | `gz-05-estacion-replay` | Estación de campo | Replay de CSV histórico | MQTT 8883 | 60 s + huecos | VM Azure |
| 06 | `gz-06-meteo-atlas` | Meteorología del predio | Atlas Weather (Azure Maps) | HTTPS → MQTT | 5 min | VM Azure |
| 07 | `gz-07-aire-openmeteo` | Calidad de aire rural | API pública Open-Meteo | HTTPS → MQTT | 10 min | VM Azure |
| 08 | `gz-08-secado-wokwi` | Secado y fermentación | Wokwi ESP32 #2 | MQTT 8883 | 20 s | Portátil (Wokwi) |
| 09 | `gz-09-riego-http` | Reservorio y riego | Puente HTTP/REST (sin MQTT) | HTTPS 443 | 2 min | VM Azure |
| 10 | `gz-10-perimetro-paho` | Perímetro y bodega | MQTT sin SDK (`paho-mqtt`) | MQTT 8883 | 30 s | VM Azure / portátil |

- **Asincronía:** ocho cadencias distintas conviven en la aplicación (el enunciado pide al menos tres).
- **Desconexión:** DEV05 tiene ventanas de silencio programadas (01:00–02:30 y 13:00–13:40, hora local);
  los dos Wokwi y DEV10 se cortan en vivo durante la sustentación.
- **Ventana analizada:** 22, 24, 26 y 28 de septiembre de 2026 (cuatro días no continuos).

---

## Estructura del repositorio

```
Parcial 1/
├── README.md
├── device-templates/        8 plantillas DTDL (JSON)
├── python/                  Flota que corre en la VM de Azure
│   ├── .env.example         Plantilla de configuración (sin secretos)
│   ├── requirements.txt
│   ├── gzcommon/            Librería común: configuración, SAS, DPS, señales y bucle
│   ├── dev0*.py / dev10*.py Un programa por dispositivo
│   ├── data/                Histórico que reproduce DEV05
│   └── tools/               Generador del histórico y análisis de la ventana
├── wokwi/
│   ├── dev01-lote-cultivo/          Firmware ESP32 #1 (PlatformIO + Wokwi)
│   └── dev08-secado-fermentacion/   Firmware ESP32 #2
├── deploy/                  Preparación de la VM, unidades systemd y control de la flota
└── docs/
    ├── Proyecto_GranjaZenon_Cacao.docx / .pdf
    ├── img/                 Arquitectura, íconos, gráficos, capturas y evidencias
    └── evidencias/          Datos agregados de la ventana y logs de la VM
```

---

## Puesta en marcha

### 1 · Configuración local

```bash
cd python
cp .env.example .env     # completar GZ_ID_SCOPE, GZ_GROUP_SAS_KEY y las claves de Azure Maps
pip install -r requirements.txt
```

Las plantillas de `device-templates/` deben estar publicadas en IoT Central antes de
arrancar la flota; si un dispositivo se conecta sin plantilla queda sin asociar.

### 2 · VM de Azure (Ubuntu 24.04)

```bash
scp -i granjazenon_key.pem deploy/install_vm.sh zenon@<IP-de-la-VM>:~/
ssh -i granjazenon_key.pem zenon@<IP-de-la-VM> 'bash ~/install_vm.sh'

# copiar el código de python/ y deploy/ a /opt/granjazenon y arrancar
ssh -i granjazenon_key.pem zenon@<IP-de-la-VM> \
  'cd /opt/granjazenon && ./deploy/flota.sh instalar && ./deploy/flota.sh arrancar'
```

Operación diaria:

```bash
./deploy/flota.sh estado          # estado y mensajes enviados por nodo
./deploy/flota.sh logs            # últimas líneas de cada log
./deploy/flota.sh seguir dev02    # seguir un nodo en vivo
./deploy/flota.sh cortar dev05    # desconexión controlada
./deploy/flota.sh reconectar dev05
```

### 3 · Wokwi (VS Code + PlatformIO + extensión Wokwi)

```bash
cp wokwi/dev01-lote-cultivo/src/iot_configs.example.h wokwi/dev01-lote-cultivo/src/iot_configs.h
cd wokwi/dev01-lote-cultivo && pio run      # luego F1 -> "Wokwi: Start Simulator"
```

Lo mismo para `wokwi/dev08-secado-fermentacion`. Después de cambiar el firmware o el
diagrama hay que detener y volver a iniciar la simulación.

---

## Seguridad de las credenciales

El enunciado exige *"credenciales solo por variable de entorno o DPS attested"*:

- Los secretos viven en `python/.env` y en `src/iot_configs.h` de cada firmware; ambos
  están en `.gitignore`. El repositorio solo publica las plantillas `.example`.
- **La clave maestra del grupo no se distribuye.** Cada dispositivo usa una clave derivada

  ```
  device_key = Base64( HMAC-SHA256( Base64Decode(clave_de_grupo), device_id ) )
  ```

  de modo que comprometer un nodo no compromete la flota.
- La clave SSH de la VM (`*.pem`) tampoco se sube.

---

## Decisiones de diseño

- **Los tres lotes comparten plantilla** porque son el mismo kit desplegado en tres sitios:
  así se superponen en un solo gráfico y se comparan.
- **Cada nodo es un servicio systemd independiente.** Si uno se cae, los demás siguen
  publicando, y se puede cortar uno solo para evidenciar la desconexión.
- **Las señales se calculan desde el reloj, no desde un contador.** Si un servicio se
  reinicia retoma la curva donde le corresponde; el único salto visible es el hueco de
  la desconexión.
- **Los puentes hacia Azure Maps y Open-Meteo degradan en vez de caerse:** si la fuente
  falla, publican el modelo local y el log registra qué fuente alimentó cada muestra.
- **DEV04 sale por WebSocket en el puerto 443** porque la línea celular del predio está
  detrás de un CGNAT que corta las sesiones TCP largas al puerto 8883.
