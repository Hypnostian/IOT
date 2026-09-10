// Copyright (c) Microsoft Corporation.
// SPDX-License-Identifier: MIT

#ifndef IOT_CONFIGS_H
#define IOT_CONFIGS_H

// Wi-Fi virtual de Wokwi
#define IOT_CONFIG_WIFI_SSID              "Wokwi-GUEST"
#define IOT_CONFIG_WIFI_PASSWORD          ""

// Sensor DHT22
#define DHT_TYPE                          DHT22
#define DHT_PIN                           15

// Azure IoT Central
#define DPS_ID_SCOPE                      "0ne00FE096B"
#define IOT_CONFIG_DEVICE_ID              "1yzbe72rbu7"
#define IOT_CONFIG_DEVICE_KEY             "6qrjG9jADBFRhypweHQ0B+uM8FkODxn9sWMD72IC96w="

// Modelo de la plantilla IoT Plug and Play
#define IOT_CONFIG_MODEL_ID               "dtmi:laboratorio1Iot:DispositivoLaboratorio1_6cv;1"

// User-agent del cliente MQTT
#define AZURE_SDK_CLIENT_USER_AGENT        "c%2F" AZ_SDK_VERSION_STRING "(ard%3Besp32)"

// Publicar telemetría cada 5 segundos
#define TELEMETRY_FREQUENCY_IN_SECONDS     5

// Duración del token SAS
#define MQTT_PASSWORD_LIFETIME_IN_MINUTES  60

#endif