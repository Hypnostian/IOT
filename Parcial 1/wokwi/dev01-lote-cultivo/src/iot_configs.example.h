// Granja Zenon - Cacao | Parcial 1
// DEV01 - Lote de cultivo 1 "Zenon Alto"  (Wokwi ESP32 #1)
//
// ATENCION: este archivo contiene la clave del dispositivo y esta en
// .gitignore. Para el repositorio publico se entrega iot_configs.example.h.
//
// La clave NO es la clave maestra del grupo: es la clave DERIVADA de este
// dispositivo, obtenida con
//     device_key = Base64(HMAC-SHA256(Base64Decode(group_key), device_id))
// que es lo mismo que calcula `az iot central device compute-device-key`.
// Se puede regenerar con:  python python/gzcommon/config.py

#ifndef IOT_CONFIGS_H
#define IOT_CONFIGS_H

// --- Wi-Fi virtual de Wokwi -------------------------------------------------
// En el predio real este nodo sale por el router 4G/LTE de la casa principal.
#define IOT_CONFIG_WIFI_SSID              "Wokwi-GUEST"
#define IOT_CONFIG_WIFI_PASSWORD          ""

// --- Sensores ---------------------------------------------------------------
#define DHT_TYPE                          DHT22
#define DHT_PIN                           15

// --- Azure IoT Central ------------------------------------------------------
#define DPS_ID_SCOPE                      "0neXXXXXXXX"          // <- Ambito de ID de tu app
#define IOT_CONFIG_DEVICE_ID              "gz-01-lote1-wokwi"
#define IOT_CONFIG_DEVICE_KEY             "clave-derivada-del-dispositivo"  // <- ver README

// --- Plantilla (Device Template) --------------------------------------------
#define IOT_CONFIG_MODEL_ID               "dtmi:granjazenon:cacao:NodoSuelo;1"

// --- Cliente MQTT -----------------------------------------------------------
#define AZURE_SDK_CLIENT_USER_AGENT        "c%2F" AZ_SDK_VERSION_STRING "(ard%3Besp32)"

// Cadencia de este nodo dentro de la flota asincrona: 15 s.
#define TELEMETRY_FREQUENCY_IN_SECONDS     15

// Vigencia del token SAS que el firmware renueva solo.
#define MQTT_PASSWORD_LIFETIME_IN_MINUTES  60

#endif
