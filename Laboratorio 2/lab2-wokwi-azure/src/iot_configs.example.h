#ifndef IOT_CONFIGS_H
#define IOT_CONFIGS_H

#define IOT_CONFIG_WIFI_SSID              "Wokwi-GUEST"
#define IOT_CONFIG_WIFI_PASSWORD          ""

#define DHT_TYPE                          DHT22
#define DHT_PIN                           15

#define DPS_ID_SCOPE                      "YOUR_ID_SCOPE"
#define IOT_CONFIG_DEVICE_ID              "lab2-wokwi-08"
#define IOT_CONFIG_DEVICE_KEY             "YOUR_DEVICE_KEY"

#define IOT_CONFIG_MODEL_ID               "dtmi:laboratorio1Iot:DispositivoLaboratorio1_6cv;1"

#define AZURE_SDK_CLIENT_USER_AGENT        "c%2F" AZ_SDK_VERSION_STRING "(ard%3Besp32)"

#define TELEMETRY_FREQUENCY_IN_SECONDS     5
#define MQTT_PASSWORD_LIFETIME_IN_MINUTES  60

#endif