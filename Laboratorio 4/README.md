# Laboratorio 4: AMQP y tercer protocolo hacia Azure IoT Central

Comparación de MQTT, AMQP y HTTPS publicando la misma telemetría del panel solar en el dispositivo
**Lab 2 Python 07** (`lab2-python-07`) de la aplicación **laboratorio-1** de Azure IoT Central.

- **Universidad:** Universidad Autónoma de Bucaramanga
- **Asignatura:** IoT + Cloud + Sistemas Distribuidos
- **Integrantes:** Juan Sebastian Lizcano Jaimes, Angie Katherine Suarez Ortiz, Miguel Angel Hernandez Quintero
- **Fecha:** octubre de 2026

## Contenido

| Ruta | Descripción |
|---|---|
| `vm/amqp_cliente.py` | Cliente AMQP 1.0 con Qpid Proton. Puerto 5671, SASL PLAIN con token SAS. |
| `vm/https_cliente.py` | Tercer protocolo: HTTPS con la API REST de IoT Hub. Modo keep-alive o conexión nueva por mensaje. |
| `vm/mqtt_cliente.py` | Línea base MQTT (paho-mqtt, QoS 1), medida con el mismo método que los otros dos. |
| `vm/comun.py` | Carga del `.env`, generación del token SAS, generador de lecturas y registro de mediciones. |
| `vm/resumen.py` | Tabla comparativa a partir de los resultados de cada protocolo. |
| `vm/verificar_puertos.sh` | Revisión de DNS, puertos 8883, 5671 y 443 y saludo TLS del puerto 5671. |
| `vm/requirements.txt` | Dependencias de Python. |
| `vm/.env.example` | Variables necesarias, sin valores reales. |
| `evidencias/capturas/` | Capturas de la VM y de IoT Central, numeradas como en el Anexo A del informe. |
| `evidencias/registros/` | CSV, resúmenes JSON y registros de texto de las pruebas. |
| `guia/laboratorio4.pdf` | Guía del laboratorio. |
| `Informe_Laboratorio_4.docx` | Informe del laboratorio. |

## Dependencias

- VM Debian 12 con Python 3.11 (la misma del Laboratorio 2).
- Paquetes del sistema para compilar Qpid Proton con TLS: `build-essential`, `python3-dev`, `python3-venv`, `libssl-dev` y `pkg-config`.
- Paquetes de Python: `python-qpid-proton`, `paho-mqtt`, `python-dotenv` y `certifi`.

La librería `azure-iot-device` para Python solo implementa MQTT y MQTT sobre WebSockets, por eso el cliente
AMQP usa Qpid Proton, el cliente AMQP 1.0 mantenido por Apache.

## Cómo reproducir

```bash
sudo apt-get install -y build-essential python3-dev python3-venv libssl-dev pkg-config
mkdir -p ~/laboratorio4 && cd ~/laboratorio4      # copiar aquí el contenido de vm/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                               # completar con los datos del dispositivo
chmod 600 .env
./verificar_puertos.sh
python amqp_cliente.py --count 10 --interval 5
python https_cliente.py --count 10 --interval 5
python https_cliente.py --count 10 --interval 5 --nueva-conexion
python mqtt_cliente.py --count 10 --interval 5
python resumen.py
```

Para ver las tramas AMQP (open, begin, attach, flow, transfer y disposition) sin exponer el token:

```bash
PN_TRACE_FRM=1 LAB4_RESULTADOS=traza python amqp_cliente.py --count 2 --interval 2 2>&1 \
  | sed -E "s/initial-response=[^]]*/initial-response=<oculto>/"
```

Los resultados quedan en `resultados/`: un CSV por protocolo con cada envío y un JSON con el resumen
(bytes de conexión, bytes por mensaje y tiempos de confirmación).

## Variables de entorno

| Variable | Uso |
|---|---|
| `IOTC_HUB_HOSTNAME` | Hostname del IoT Hub asignado por DPS al dispositivo. |
| `IOTC_DEVICE_ID` | Device ID del dispositivo en IoT Central. |
| `IOTC_DEVICE_KEY` | Clave primaria del dispositivo. |

El archivo `.env` no se sube al repositorio.

## Cómo se genera el token SAS

1. Recurso: `{IOTC_HUB_HOSTNAME}/devices/{IOTC_DEVICE_ID}`, codificado para URL.
2. Expiración: segundos Unix actuales más 3600.
3. Firma: HMAC-SHA256 de `recurso + "\n" + expiración`, usando como llave la clave del dispositivo decodificada en Base64. El resultado se codifica en Base64 y luego para URL.
4. Token: `SharedAccessSignature sr={recurso}&sig={firma}&se={expiración}`.

Cada protocolo usa el mismo token de forma distinta:

- **MQTT:** contraseña del CONNECT. El username es `{hub}/{deviceId}/?api-version=2021-04-12`.
- **AMQP:** contraseña de SASL PLAIN. El usuario es `{deviceId}@sas.{nombre-del-hub}`.
- **HTTPS:** encabezado `Authorization` de cada petición POST.

## Resultados

| Protocolo | Mensajes OK | Conexión | Bytes de conexión env/rec | Bytes por mensaje env/rec | Confirmación prom. | Creación a IoT Hub prom. |
|---|---|---|---|---|---|---|
| MQTT 8883 | 10/10 | 203 ms | 963 / 3620 | 263 / 33 | 141 ms | 107 ms |
| AMQP 5671 | 10/10 | 285 ms | 1216 / 4200 | 337 / 55 | 142 ms | 109 ms |
| HTTPS keep-alive | 10/10 | 129 ms | 611 / 3524 | 766 / 93 | 144 ms | 114 ms |
| HTTPS conexión nueva | 10/10 | 135 ms | 611 / 3524 | 1379 / 3617 | 188 ms | 155 ms |

Las cuatro variables (PotenciaGenerada, TemperaturaDelPanel, VoltajeDeSalida y CorrienteDeSalida) llegaron
en los tres casos a la misma aplicación. El payload JSON pesa entre 99 y 101 bytes en todos. Los bytes se
midieron con `ss` sobre la conexión TCP, así que incluyen TLS. La columna de creación a IoT Hub compara
`_eventcreationtime`, que envía el cliente, con `_timestamp`, que asigna IoT Hub.

## Evidencias

Capturas en `evidencias/capturas/`:

| Archivo | Contenido |
|---|---|
| `01_puertos_y_tls.png` | DNS del hub, puertos 8883, 5671 y 443 abiertos y TLS 1.2 en el 5671. |
| `02_amqp_inicio.png`, `03_amqp_final.png` | Corrida AMQP: conexión, crédito de 50 mensajes, 10 entregas aceptadas. |
| `04_central_amqp_datos.png`, `05_central_amqp_json.png` | Serie AMQP en Datos sin procesar y JSON de un mensaje. |
| `06_amqp_tramas.png` | Tramas AMQP con el token oculto. |
| `07_https_inicio.png`, `08_https_final.png` | Corrida HTTPS con keep-alive (HTTP 204). |
| `09_https_conexion_nueva.png` | Corrida HTTPS con un saludo TLS por mensaje. |
| `10_central_https_datos.png` | Series HTTPS en IoT Central. |
| `11_mqtt_inicio.png`, `12_mqtt_final.png`, `13_central_mqtt_datos.png` | Línea base MQTT. |
| `14_resumen_comparativo.png` | Salida de `resumen.py`. |
| `15_central_explorador_datos.png` | Potencia Generada de Lab 2 Python 07 en el Explorador de datos. |

Registros en `evidencias/registros/`:

| Archivo | Contenido |
|---|---|
| `traza_amqp.log` | Tramas AMQP de una corrida de dos mensajes, con el token oculto. |
| `verificacion_puertos.log` | Salida de `verificar_puertos.sh`. |
| `latencia_creacion_a_iot_hub.csv` | Tiempo de creación a registro en IoT Hub de cada mensaje. |
| `resultados/` | CSV y JSON generados por los clientes. |
