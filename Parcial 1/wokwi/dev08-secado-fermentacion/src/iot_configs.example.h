// Granja Zenon - Cacao | Parcial 1
// DEV08 - Secado y fermentacion "Marinela"  (Wokwi ESP32 #2)
//
// Segunda instancia de Wokwi. Es un origen DISTINTO del DEV01: otro
// dispositivo, otra plantilla, otro firmware y otra cadencia.
//
// ATENCION: contiene la clave derivada de este dispositivo y esta en
// .gitignore. Se regenera con:  python python/gzcommon/config.py

#ifndef IOT_CONFIGS_H
#define IOT_CONFIGS_H

// --- Wi-Fi virtual de Wokwi -------------------------------------------------
// En el predio real este nodo esta en la marquesina, a 40 m de la casa, y se
// cuelga del mismo router 4G/LTE mediante un repetidor.
#define IOT_CONFIG_WIFI_SSID              "Wokwi-GUEST"
#define IOT_CONFIG_WIFI_PASSWORD          ""

// --- Sensores ---------------------------------------------------------------
#define DHT_TYPE                          DHT22
#define DHT_PIN                           15

// --- Azure IoT Central ------------------------------------------------------
#define DPS_ID_SCOPE                      "0neXXXXXXXX"          // <- Ambito de ID de tu app
#define IOT_CONFIG_DEVICE_ID              "gz-08-secado-wokwi"
#define IOT_CONFIG_DEVICE_KEY             "clave-derivada-del-dispositivo"  // <- ver README

// --- Plantilla (Device Template) --------------------------------------------
#define IOT_CONFIG_MODEL_ID               "dtmi:granjazenon:cacao:SecadoFermentacion;1"

// --- Cliente MQTT -----------------------------------------------------------
#define AZURE_SDK_CLIENT_USER_AGENT        "c%2F" AZ_SDK_VERSION_STRING "(ard%3Besp32)"

// Cadencia de este nodo dentro de la flota asincrona: 20 s.
#define TELEMETRY_FREQUENCY_IN_SECONDS     20

#define MQTT_PASSWORD_LIFETIME_IN_MINUTES  60

#endif
