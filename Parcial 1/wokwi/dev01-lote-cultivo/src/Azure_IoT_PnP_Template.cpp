// Granja Zenon - Cacao | Parcial 1
// DEV01 - Lote de cultivo 1 "Zenon Alto"
//
// Origen de envio : Wokwi ESP32 #1 (Arduino + Azure SDK for C)
// Plantilla       : GZ Nodo de Suelo (dtmi:granjazenon:cacao:NodoSuelo;1)
// Intervalo       : 15 s
//
// Sensores del nodo (ver diagram.json):
//   GPIO 34  potenciometro  -> humedad volumetrica del suelo   (METER TEROS 12)
//   GPIO 35  potenciometro  -> conductividad electrica del suelo (TEROS 12)
//   GPIO 32  NTC            -> temperatura del suelo a 20 cm
//   GPIO 33  fotorresistor  -> radiacion PAR bajo el sombrio   (Apogee SQ-500)
//   GPIO 15  DHT22          -> temperatura y HR del canopy     (MLX90614 real)
//   GPIO  2  LED            -> electrovalvula de riego del lote (actuador)
//
// Basado en el ejemplo oficial Azure_IoT_PnP_Template de Microsoft
// (SPDX-License-Identifier: MIT), adaptado al escenario del cacao.

#include <stdlib.h>
#include <Arduino.h>
#include <math.h>
#include <stdarg.h>

#include <az_core.h>
#include <az_iot.h>

#include "AzureIoT.h"
#include "Azure_IoT_PnP_Template.h"

#include <az_precondition_internal.h>

#include <Adafruit_Sensor.h>
#include <DHT.h>
#include <WiFi.h>
#include "iot_configs.h"

/* --- Identidad del modelo --- */
#define AZURE_PNP_MODEL_ID "dtmi:granjazenon:cacao:NodoSuelo;1"

/* --- Informacion del dispositivo --- */
#define SAMPLE_DEVICE_INFORMATION_NAME                 "deviceInformation"
#define SAMPLE_MANUFACTURER_PROPERTY_NAME              "manufacturer"
#define SAMPLE_MODEL_PROPERTY_NAME                     "model"
#define SAMPLE_SOFTWARE_VERSION_PROPERTY_NAME          "swVersion"
#define SAMPLE_OS_NAME_PROPERTY_NAME                   "osName"
#define SAMPLE_PROCESSOR_ARCHITECTURE_PROPERTY_NAME    "processorArchitecture"
#define SAMPLE_PROCESSOR_MANUFACTURER_PROPERTY_NAME    "processorManufacturer"
#define SAMPLE_TOTAL_STORAGE_PROPERTY_NAME             "totalStorage"
#define SAMPLE_TOTAL_MEMORY_PROPERTY_NAME              "totalMemory"

#define SAMPLE_MANUFACTURER_PROPERTY_VALUE             "Granja Zenon"
#define SAMPLE_MODEL_PROPERTY_VALUE                    "GZ-SoilNode ESP32 v1"
#define SAMPLE_VERSION_PROPERTY_VALUE                  "1.0.0"
#define SAMPLE_OS_NAME_PROPERTY_VALUE                  "FreeRTOS"
#define SAMPLE_ARCHITECTURE_PROPERTY_VALUE             "ESP32-WROOM-32"
#define SAMPLE_PROCESSOR_MANUFACTURER_PROPERTY_VALUE   "ESPRESSIF"
#define SAMPLE_TOTAL_STORAGE_PROPERTY_VALUE            4096
#define SAMPLE_TOTAL_MEMORY_PROPERTY_VALUE             8192

/* --- Nombres de telemetria: deben coincidir EXACTAMENTE con el DTDL --- */
#define TELEMETRY_HUMEDAD_SUELO        "humedadSuelo"
#define TELEMETRY_TEMP_SUELO           "tempSuelo"
#define TELEMETRY_CE_SUELO             "ceSuelo"
#define TELEMETRY_TEMP_CANOPY          "tempCanopy"
#define TELEMETRY_PAR_PPFD             "parPPFD"
#define TELEMETRY_BATERIA              "bateria"
#define TELEMETRY_RSSI                 "rssi"

/* --- Propiedades reportadas --- */
#define PROP_LOTE                      "lote"
#define PROP_VARIEDAD                  "variedadCacao"
#define PROP_AREA_HA                   "areaHa"
#define PROP_PROFUNDIDAD               "profundidadSensorCm"

#define PROP_LOTE_VALOR                "Lote 1 - Zenon Alto"
#define PROP_VARIEDAD_VALOR            "CCN-51"
#define PROP_AREA_HA_VALOR             3.2
#define PROP_PROFUNDIDAD_VALOR         20

/* --- Propiedades escribibles --- */
#define WRITABLE_UMBRAL_RIEGO          "umbralRiegoVWC"
#define WRITABLE_INTERVALO             "intervaloTelemetriaSeg"
#define WRITABLE_PROPERTY_RESPONSE_SUCCESS  "success"

/* --- Comandos --- */
static az_span COMMAND_CALIBRAR = AZ_SPAN_FROM_STR("CalibrarSensorSuelo");
static az_span COMMAND_RIEGO    = AZ_SPAN_FROM_STR("ActivarRiegoLote");
#define COMMAND_RESPONSE_CODE_ACCEPTED   200
#define COMMAND_RESPONSE_CODE_REJECTED   404

/* --- Pines --- */
#define PIN_HUMEDAD_SUELO   34
#define PIN_CE_SUELO        35
#define PIN_TEMP_SUELO      32
#define PIN_PAR             33
#define PIN_VALVULA_RIEGO    2

#define DOUBLE_DECIMAL_PLACE_DIGITS 2

/* --- Returns --- */
#define RESULT_OK       0
#define RESULT_ERROR    __LINE__

#define EXIT_IF_TRUE(condition, retcode, message, ...)                       \
  do {                                                                      \
    if (condition) { LogError(message, ##__VA_ARGS__ ); return retcode; }   \
  } while (0)

#define EXIT_IF_AZ_FAILED(azresult, retcode, message, ...)                  \
  EXIT_IF_TRUE(az_result_failed(azresult), retcode, message, ##__VA_ARGS__ )

/* --- Estado --- */
#define DATA_BUFFER_SIZE 1024
static uint8_t data_buffer[DATA_BUFFER_SIZE];
static uint32_t telemetry_send_count = 0;

static size_t telemetry_frequency_in_seconds = TELEMETRY_FREQUENCY_IN_SECONDS;
static time_t last_telemetry_send_time = INDEFINITE_TIME;

// Estado de la electrovalvula. Puede abrirse por tres motivos, y cualquiera
// de ellos enciende el LED azul del simulador:
//   1. Riego programado del predio: 05:30-07:00 y 17:00-18:30, las MISMAS
//      ventanas en que el reservorio DEV09 enciende la bomba.
//   2. Comando ActivarRiegoLote enviado desde IoT Central.
//   3. Logica local: la humedad cae por debajo de umbralRiegoVWC (propiedad
//      escribible), con histeresis de 6 puntos para no abrir y cerrar sin fin.
static bool riego_abierto = false;
static bool riego_por_comando = false;
static bool riego_por_umbral = false;
static bool riego_programado = false;
static float umbral_riego_vwc = 24.0f;

// %VWC que aporta el riego en curso cuando NO es el programado (el programado
// ya esta incluido en la curva base). Crece mientras la valvula esta abierta y
// se disipa despues, igual que el agua en el perfil del suelo.
static float aporte_riego = 0.0f;
static time_t ultimo_calculo_riego = INDEFINITE_TIME;
static uint32_t calibraciones = 0;

static DHT dht(DHT_PIN, DHT_TYPE);

/* --- Prototipos --- */
static int generate_telemetry_payload(uint8_t*, size_t, size_t*);
static int generate_device_info_payload(az_iot_hub_client const*, uint8_t*, size_t, size_t*);
static int consume_properties_and_generate_response(azure_iot_t*, az_span, uint8_t*, size_t, size_t*);

/* ======================= Funciones publicas ======================= */
void azure_pnp_init() { }

const az_span azure_pnp_get_model_id()
{
  return AZ_SPAN_FROM_STR(AZURE_PNP_MODEL_ID);
}

void azure_pnp_set_telemetry_frequency(size_t frequency_in_seconds)
{
  telemetry_frequency_in_seconds = frequency_in_seconds;
  LogInfo("Intervalo de telemetria: cada %d segundos.", telemetry_frequency_in_seconds);
}

void initSensors()
{
  dht.begin();
  pinMode(PIN_HUMEDAD_SUELO, INPUT);
  pinMode(PIN_CE_SUELO, INPUT);
  pinMode(PIN_TEMP_SUELO, INPUT);
  pinMode(PIN_PAR, INPUT);
  pinMode(PIN_VALVULA_RIEGO, OUTPUT);
  digitalWrite(PIN_VALVULA_RIEGO, LOW);
  analogReadResolution(12);
  LogInfo("Sensores del nodo de suelo inicializados (lote 1).");
}

int azure_pnp_send_telemetry(azure_iot_t* azure_iot)
{
  _az_PRECONDITION_NOT_NULL(azure_iot);

  time_t now = time(NULL);
  if (now == INDEFINITE_TIME)
  {
    LogError("No se pudo leer la hora para controlar la telemetria.");
    return RESULT_ERROR;
  }

  if (last_telemetry_send_time == INDEFINITE_TIME ||
      difftime(now, last_telemetry_send_time) >= telemetry_frequency_in_seconds)
  {
    size_t payload_size;
    last_telemetry_send_time = now;

    if (generate_telemetry_payload(data_buffer, DATA_BUFFER_SIZE, &payload_size) != RESULT_OK)
    {
      LogError("Fallo generando el payload de telemetria.");
      return RESULT_ERROR;
    }
    if (azure_iot_send_telemetry(azure_iot, az_span_create(data_buffer, payload_size)) != 0)
    {
      LogError("Fallo enviando la telemetria.");
      return RESULT_ERROR;
    }
  }
  return RESULT_OK;
}

int azure_pnp_send_device_info(azure_iot_t* azure_iot, uint32_t request_id)
{
  _az_PRECONDITION_NOT_NULL(azure_iot);
  int result;
  size_t length;

  result = generate_device_info_payload(&azure_iot->iot_hub_client, data_buffer, DATA_BUFFER_SIZE, &length);
  EXIT_IF_TRUE(result != RESULT_OK, RESULT_ERROR, "Fallo generando la info del dispositivo.");

  result = azure_iot_send_properties_update(azure_iot, request_id, az_span_create(data_buffer, length));
  EXIT_IF_TRUE(result != RESULT_OK, RESULT_ERROR, "Fallo enviando las propiedades reportadas.");

  return RESULT_OK;
}

int azure_pnp_handle_command_request(azure_iot_t* azure_iot, command_request_t command)
{
  _az_PRECONDITION_NOT_NULL(azure_iot);
  uint16_t response_code = COMMAND_RESPONSE_CODE_REJECTED;

  if (az_span_is_content_equal(command.command_name, COMMAND_CALIBRAR))
  {
    calibraciones++;
    LogInfo("COMANDO CalibrarSensorSuelo ejecutado (total: %u).", calibraciones);
    response_code = COMMAND_RESPONSE_CODE_ACCEPTED;
  }
  else if (az_span_is_content_equal(command.command_name, COMMAND_RIEGO))
  {
    // IoT Central puede mandar el booleano suelto o dentro de un objeto.
    const uint8_t* p = az_span_ptr(command.payload);
    const int32_t n = az_span_size(command.payload);
    bool encender = false, valido = false;

    for (int32_t i = 0; i <= n - 4; ++i)
    {
      if (memcmp(p + i, "true", 4) == 0) { encender = true; valido = true; break; }
    }
    if (!valido)
    {
      for (int32_t i = 0; i <= n - 5; ++i)
      {
        if (memcmp(p + i, "false", 5) == 0) { encender = false; valido = true; break; }
      }
    }

    if (valido)
    {
      // El comando solo gobierna su propia causa de apertura: si en ese
      // momento hay riego programado o por umbral, la valvula sigue abierta.
      riego_por_comando = encender;
      if (encender)
      {
        riego_abierto = true;
        digitalWrite(PIN_VALVULA_RIEGO, HIGH);
      }
      LogInfo("COMANDO ActivarRiegoLote: riego manual %s.",
              encender ? "ACTIVADO" : "DESACTIVADO");
      response_code = COMMAND_RESPONSE_CODE_ACCEPTED;
    }
    else
    {
      LogError("ActivarRiegoLote recibio un payload no valido.");
    }
  }
  else
  {
    LogError("Comando no reconocido (%.*s).",
             az_span_size(command.command_name), az_span_ptr(command.command_name));
  }

  return azure_iot_send_command_response(azure_iot, command.request_id, response_code, AZ_SPAN_EMPTY);
}

int azure_pnp_handle_properties_update(azure_iot_t* azure_iot, az_span properties, uint32_t request_id)
{
  _az_PRECONDITION_NOT_NULL(azure_iot);
  _az_PRECONDITION_VALID_SPAN(properties, 1, false);

  int result;
  size_t length;

  result = consume_properties_and_generate_response(azure_iot, properties, data_buffer, DATA_BUFFER_SIZE, &length);
  EXIT_IF_TRUE(result != RESULT_OK, RESULT_ERROR, "Fallo generando el acuse de propiedades.");

  result = azure_iot_send_properties_update(azure_iot, request_id, az_span_create(data_buffer, length));
  EXIT_IF_TRUE(result != RESULT_OK, RESULT_ERROR, "Fallo enviando las propiedades reportadas.");

  return RESULT_OK;
}

/* ================= Modelo temporal del lote ========================= */
/*
 * Por que el firmware calcula la curva y no se limita a leer el sensor
 * -------------------------------------------------------------------
 * Los componentes de Wokwi son ESTATICOS: el DHT22 devuelve siempre la
 * temperatura fijada en diagram.json, el NTC y el fotorresistor lo mismo, y
 * los potenciometros se quedan donde se dejen. Si el firmware se limitara a
 * leerlos, la serie en IoT Central seria una linea plana, inservible para la
 * ventana de 4 dias.
 *
 * Asi que el nodo hace lo mismo que los de Python: reproduce el ciclo diario
 * del lote a partir del RELOJ, y usa los sensores como AJUSTE MANUAL encima
 * de esa curva. Mover un potenciometro sigue teniendo efecto inmediato y
 * visible durante la sustentacion, pero si nadie toca nada la serie
 * evoluciona sola, como lo hace un lote de verdad.
 */

// Hora local decimal del predio (America/Bogota, UTC-5 fijo).
static float hora_local(time_t ahora)
{
  if (ahora == INDEFINITE_TIME) { return 12.0f; }
  return fmodf((float)(ahora / 3600.0f) - 5.0f + 24.0f, 24.0f);
}

// Curva solar 0..1: 0 de noche, maximo a media tarde.
static float curva_solar(time_t ahora)
{
  const float h = hora_local(ahora);
  const float amanecer = 5.9f, atardecer = 18.2f;
  if (h < amanecer || h > atardecer) { return 0.0f; }
  return sinf(((h - amanecer) / (atardecer - amanecer)) * PI);
}

// Ajuste manual de un potenciometro: -0.5 a +0.5 con el centro en reposo.
static float ajuste_pot(int pin)
{
  return (analogRead(pin) / 4095.0f) - 0.5f;
}

/* --- Ruido de sensor -------------------------------------------------- */
/*
 * Sin esto la serie sale matematicamente perfecta, y se nota: un sensor real
 * nunca entrega dos lecturas identicas. Ademas las curvas del proceso son
 * lentas (la temperatura del suelo cambia decimas por hora), asi que entre dos
 * muestras separadas 15 s el valor pareceria congelado.
 *
 * El ruido se deriva del RELOJ, no de random(), para que sea reproducible: un
 * reinicio del simulador no produce un salto artificial en la grafica.
 *
 * Se suman dos octavas: una rapida de 4 minutos, que da la textura visible
 * entre muestras consecutivas, y una lenta de 30 minutos, que da la deriva.
 */
static uint32_t mezclar(uint32_t x)
{
  x ^= x >> 16; x *= 0x7feb352dU;
  x ^= x >> 15; x *= 0x846ca68bU;
  x ^= x >> 16;
  return x;
}

static float aleatorio_estable(uint32_t semilla)
{
  return ((float)(mezclar(semilla) & 0xFFFFu) / 32767.5f) - 1.0f;
}

static float octava(uint32_t canal, time_t ahora, uint32_t periodo)
{
  const uint32_t t = (uint32_t)(ahora < 0 ? 0 : ahora);
  const uint32_t tramo = t / periodo;
  const float frac = (float)(t % periodo) / (float)periodo;
  const uint32_t base = canal * 2654435761u + periodo * 40503u;
  const float a = aleatorio_estable(base + tramo);
  const float b = aleatorio_estable(base + tramo + 1u);
  const float s = (1.0f - cosf(frac * (float)PI)) * 0.5f;  // suavizado coseno
  return a + (b - a) * s;
}

static float ruido(uint32_t canal, time_t ahora, float amplitud)
{
  if (ahora == INDEFINITE_TIME) { return 0.0f; }
  // Tres octavas. La de 45 s es la que hace que dos muestras consecutivas
  // (separadas 15-20 s) se distingan, como en un sensor real; las de 4 y 30
  // minutos aportan la deriva de fondo.
  return (octava(canal, ahora, 45u)   * 0.30f +
          octava(canal, ahora, 240u)  * 0.35f +
          octava(canal, ahora, 1800u) * 0.35f) * amplitud;
}

/* ======================= Lectura de sensores ======================= */

// Humedad volumetrica. El TEROS 12 mide 0..70 % VWC, pero el rango util de un
// suelo de cacao va de 12 a 48 %. El perfil se seca durante el dia por
// evapotranspiracion y el riego lo recarga.
// Ventanas del riego programado del predio (hora local). Son las mismas en
// que el reservorio DEV09 enciende la bomba, asi que en IoT Central se ve la
// bomba arrancar y, a la vez, subir la humedad de este lote.
static bool en_ventana_de_riego(float h)
{
  return (h >= 5.5f && h < 7.0f) || (h >= 17.0f && h < 18.5f);
}

/*
 * Humedad del perfil a 20 cm segun el riego programado:
 *   - tras cada riego el suelo queda a capacidad de campo (~36 %VWC),
 *   - despues se seca de forma exponencial hacia ~24 %VWC (tau = 9 h),
 *   - con sol fuerte la evapotranspiracion lo seca un poco mas.
 * El resultado es el diente de sierra tipico de una sonda de humedad en un
 * lote con riego por goteo: subida rapida dos veces al dia y descenso lento.
 */
static float curva_riego_programado(time_t ahora, float sol)
{
  const float h = hora_local(ahora);
  const float capacidad = 36.0f;
  const float seco = 24.0f;
  const float tau_h = 9.0f;

  // Horas desde que termino el ultimo riego programado.
  float horas_secando;
  if (h >= 18.5f)      { horas_secando = h - 18.5f; }
  else if (h >= 7.0f)  { horas_secando = h - 7.0f; }
  else if (h >= 5.5f)  { horas_secando = 0.0f; }
  else                 { horas_secando = h + (24.0f - 18.5f); }

  float vwc = seco + (capacidad - seco) * expf(-horas_secando / tau_h);

  if (en_ventana_de_riego(h))
  {
    // Durante el riego el perfil sube desde donde estaba hasta capacidad.
    // Antes del riego de la manana llevaba 11 h secandose; antes del de la
    // tarde, 10 h.
    const bool manana = (h < 12.0f);
    const float inicio = manana ? 5.5f : 17.0f;
    const float antes = manana ? 11.0f : 10.0f;
    const float vwc_antes = seco + (capacidad - seco) * expf(-antes / tau_h);
    float avance = (h - inicio) / 1.5f;
    if (avance > 1.0f) { avance = 1.0f; }
    const float suave = (1.0f - cosf(avance * (float)PI)) * 0.5f;
    vwc = vwc_antes + (capacidad - vwc_antes) * suave;
  }

  return vwc - 1.5f * sol;
}

// Humedad sin el aporte del riego manual o por umbral (ese se suma aparte).
static float leer_humedad_suelo(float sol, time_t ahora)
{
  float vwc = curva_riego_programado(ahora, sol);
  vwc += ajuste_pot(PIN_HUMEDAD_SUELO) * 24.0f;   // +/-12 puntos de ajuste
  vwc += ruido(1, ahora, 1.8f);
  return vwc;
}

/*
 * Decide si la electrovalvula esta abierta y calcula el agua que aporta el
 * riego que NO es el programado. Se llama una vez por muestra.
 */
static float actualizar_riego(time_t ahora, float vwc_sin_aporte)
{
  // Tiempo desde el calculo anterior, acotado: tras una resincronizacion de
  // NTP el reloj del dispositivo puede saltar hacia delante.
  float dt = 0.0f;
  if (ultimo_calculo_riego != INDEFINITE_TIME && ahora != INDEFINITE_TIME)
  {
    dt = (float)difftime(ahora, ultimo_calculo_riego);
    if (dt < 0.0f)  { dt = 0.0f; }
    if (dt > 90.0f) { dt = 90.0f; }
  }
  ultimo_calculo_riego = ahora;

  // 1. Riego programado.
  const bool programado = en_ventana_de_riego(hora_local(ahora));
  if (programado != riego_programado)
  {
    riego_programado = programado;
    LogInfo("Riego PROGRAMADO %s (05:30-07:00 y 17:00-18:30, igual que la bomba DEV09).",
            programado ? "INICIADO" : "TERMINADO");
  }

  // 3. Logica local por umbral, con histeresis de 6 puntos.
  const float vwc_actual = vwc_sin_aporte + aporte_riego;
  if (!riego_por_umbral && vwc_actual < umbral_riego_vwc)
  {
    riego_por_umbral = true;
    LogInfo("Humedad %.1f %%VWC bajo el umbral %.1f: riego AUTOMATICO iniciado.",
            vwc_actual, umbral_riego_vwc);
  }
  else if (riego_por_umbral && vwc_actual > umbral_riego_vwc + 6.0f)
  {
    riego_por_umbral = false;
    LogInfo("Humedad %.1f %%VWC recuperada: riego automatico terminado.", vwc_actual);
  }

  // El agua del riego manual o automatico se acumula mientras la valvula esta
  // abierta (~1,2 %VWC por minuto, hasta 10 puntos) y se disipa despues
  // (~0,3 por minuto). El programado no suma aqui: ya esta en la curva base.
  const bool extra = riego_por_comando || riego_por_umbral;
  if (extra)
  {
    aporte_riego += 0.02f * dt;
    if (aporte_riego > 10.0f) { aporte_riego = 10.0f; }
  }
  else
  {
    aporte_riego -= 0.005f * dt;
    if (aporte_riego < 0.0f) { aporte_riego = 0.0f; }
  }

  // El LED azul del simulador es la electrovalvula.
  const bool abierta = programado || extra;
  if (abierta != riego_abierto)
  {
    riego_abierto = abierta;
    digitalWrite(PIN_VALVULA_RIEGO, abierta ? HIGH : LOW);
    LogInfo("Electrovalvula %s.", abierta ? "ABIERTA (LED azul encendido)" : "CERRADA");
  }
  return aporte_riego;
}

// CE del suelo: 0.1 a 4.5 dS/m. Sube cuando el perfil se seca, porque las
// sales se concentran. El cacao es sensible a la salinidad: por encima de
// 3 dS/m se afecta la absorcion de agua.
static float leer_ce_suelo(float humedad, time_t ahora)
{
  float ce = 1.1f + (30.0f - humedad) * 0.035f;
  ce += ajuste_pot(PIN_CE_SUELO) * 2.0f;          // +/-1 dS/m de ajuste
  ce += ruido(3, ahora, 0.10f);
  if (riego_abierto) { ce -= 0.22f; }
  if (ce < 0.1f) { ce = 0.1f; }
  if (ce > 4.5f) { ce = 4.5f; }
  return ce;
}

// Temperatura del suelo a 20 cm: amortiguada y retrasada unas 3 h respecto
// del aire. El NTC entra como ajuste fino sobre esa curva.
static float leer_temp_suelo(time_t ahora)
{
  float tc = 22.4f + 3.1f * curva_solar(ahora - 3 * 3600);

  const int lectura = analogRead(PIN_TEMP_SUELO);
  const float v = (lectura / 4095.0f) * 3.3f;
  if (v > 0.01f && v < 3.29f)
  {
    const float r_ntc = 10000.0f * (v / (3.3f - v));
    const float tk = 1.0f / ((1.0f / 298.15f) +
                             (1.0f / 3950.0f) * logf(r_ntc / 10000.0f));
    tc += ((tk - 273.15f) - 23.0f) * 0.6f;   // a 23 C no altera la curva
  }
  tc += ruido(2, ahora, 0.45f);
  return tc;
}

// PAR bajo el sombrio. El sensor real es un Apogee SQ-500 (0..2500 umol/m2/s);
// bajo sombrio de cacao lo habitual son 400..900 al mediodia. El fotorresistor
// actua como regulador de la transmision del dosel.
static float leer_par(float sol, time_t ahora)
{
  const float transmision = 0.35f + (analogRead(PIN_PAR) / 4095.0f) * 0.25f;
  float par = 1850.0f * sol * transmision;
  par *= (1.0f + ruido(4, ahora, 0.14f));   // el paso de nubes sobre el lote
  if (par < 0.0f) { par = 0.0f; }
  return par;
}

/* ======================= Payload de telemetria ======================= */
static int generate_telemetry_payload(uint8_t* payload_buffer, size_t payload_buffer_size, size_t* payload_buffer_length)
{
  az_json_writer jw;
  az_result rc;
  az_span payload_buffer_span = az_span_create(payload_buffer, payload_buffer_size);

  const time_t ahora = time(NULL);
  const float sol = curva_solar(ahora);

  // Humedad = curva del riego programado + potenciometro + ruido, mas el agua
  // del riego manual o automatico si lo hay.
  const float humedad_base = leer_humedad_suelo(sol, ahora);
  float humedad_suelo = humedad_base + actualizar_riego(ahora, humedad_base);
  if (humedad_suelo < 8.0f)  { humedad_suelo = 8.0f; }
  if (humedad_suelo > 48.0f) { humedad_suelo = 48.0f; }

  const float ce_suelo      = leer_ce_suelo(humedad_suelo, ahora);
  const float temp_suelo    = leer_temp_suelo(ahora);
  const float par_ppfd      = leer_par(sol, ahora);

  // Canopy: sigue al aire pero con calentamiento radiativo al sol. El DHT22
  // entra como ajuste manual: en su valor de reposo no altera la curva.
  float temp_canopy = 21.0f + 9.5f * sol + ruido(5, ahora, 0.9f);
  const float dht_t = dht.readTemperature();
  if (!isnan(dht_t)) { temp_canopy += (dht_t - 26.0f) * 0.5f; }

  // Bateria: nodo solar. Se recarga de dia y se descarga de noche.
  int bateria = (int)(62.0f + 34.0f * sol + ruido(6, ahora, 3.0f));
  if (bateria > 100) { bateria = 100; }
  if (bateria < 5)   { bateria = 5; }

  // En Wokwi el RSSI es constante, asi que se le suma la variacion tipica de
  // un enlace Wi-Fi real a 100 m de la antena sectorial.
  const int rssi = WiFi.isConnected()
      ? (int)(WiFi.RSSI() + ruido(7, ahora, 9.0f))
      : -110;


  rc = az_json_writer_init(&jw, payload_buffer_span, NULL);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo iniciando el escritor JSON.");
  rc = az_json_writer_append_begin_object(&jw);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo abriendo el objeto JSON.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_HUMEDAD_SUELO));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con humedadSuelo.");
  rc = az_json_writer_append_double(&jw, humedad_suelo, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de humedadSuelo.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_TEMP_SUELO));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con tempSuelo.");
  rc = az_json_writer_append_double(&jw, temp_suelo, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de tempSuelo.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_CE_SUELO));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con ceSuelo.");
  rc = az_json_writer_append_double(&jw, ce_suelo, 2);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de ceSuelo.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_TEMP_CANOPY));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con tempCanopy.");
  rc = az_json_writer_append_double(&jw, temp_canopy, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de tempCanopy.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_PAR_PPFD));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con parPPFD.");
  rc = az_json_writer_append_double(&jw, par_ppfd, 0);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de parPPFD.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_BATERIA));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con bateria.");
  rc = az_json_writer_append_int32(&jw, bateria);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de bateria.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_RSSI));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con rssi.");
  rc = az_json_writer_append_int32(&jw, rssi);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de rssi.");

  rc = az_json_writer_append_end_object(&jw);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo cerrando el objeto JSON.");

  payload_buffer_span = az_json_writer_get_bytes_used_in_destination(&jw);
  if ((payload_buffer_size - az_span_size(payload_buffer_span)) < 1)
  {
    LogError("No cabe el terminador nulo del payload.");
    return RESULT_ERROR;
  }
  payload_buffer[az_span_size(payload_buffer_span)] = null_terminator;
  *payload_buffer_length = az_span_size(payload_buffer_span);

  telemetry_send_count++;
  LogInfo("TX #%u -> %s", telemetry_send_count, payload_buffer);
  return RESULT_OK;
}

/* ======================= Propiedades reportadas ======================= */
static int generate_device_info_payload(az_iot_hub_client const* hub_client, uint8_t* payload_buffer, size_t payload_buffer_size, size_t* payload_buffer_length)
{
  az_json_writer jw;
  az_result rc;
  az_span payload_buffer_span = az_span_create(payload_buffer, payload_buffer_size);

  rc = az_json_writer_init(&jw, payload_buffer_span, NULL);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo iniciando el escritor JSON.");
  rc = az_json_writer_append_begin_object(&jw);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo abriendo el objeto JSON.");

  // --- Propiedades propias del escenario ---
  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(PROP_LOTE));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con lote.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(PROP_LOTE_VALOR));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de lote.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(PROP_VARIEDAD));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con variedadCacao.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(PROP_VARIEDAD_VALOR));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de variedadCacao.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(PROP_AREA_HA));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con areaHa.");
  rc = az_json_writer_append_double(&jw, PROP_AREA_HA_VALOR, 2);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de areaHa.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(PROP_PROFUNDIDAD));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con profundidadSensorCm.");
  rc = az_json_writer_append_int32(&jw, PROP_PROFUNDIDAD_VALOR);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de profundidadSensorCm.");

  // --- Componente estandar deviceInformation ---
  rc = az_iot_hub_client_properties_writer_begin_component(hub_client, &jw, AZ_SPAN_FROM_STR(SAMPLE_DEVICE_INFORMATION_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo abriendo deviceInformation.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_MANUFACTURER_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con manufacturer.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(SAMPLE_MANUFACTURER_PROPERTY_VALUE));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de manufacturer.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_MODEL_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con model.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(SAMPLE_MODEL_PROPERTY_VALUE));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de model.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_SOFTWARE_VERSION_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con swVersion.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(SAMPLE_VERSION_PROPERTY_VALUE));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de swVersion.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_OS_NAME_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con osName.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(SAMPLE_OS_NAME_PROPERTY_VALUE));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de osName.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_PROCESSOR_ARCHITECTURE_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con processorArchitecture.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(SAMPLE_ARCHITECTURE_PROPERTY_VALUE));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de processorArchitecture.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_PROCESSOR_MANUFACTURER_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con processorManufacturer.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(SAMPLE_PROCESSOR_MANUFACTURER_PROPERTY_VALUE));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de processorManufacturer.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_TOTAL_STORAGE_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con totalStorage.");
  rc = az_json_writer_append_double(&jw, SAMPLE_TOTAL_STORAGE_PROPERTY_VALUE, DOUBLE_DECIMAL_PLACE_DIGITS);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de totalStorage.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(SAMPLE_TOTAL_MEMORY_PROPERTY_NAME));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con totalMemory.");
  rc = az_json_writer_append_double(&jw, SAMPLE_TOTAL_MEMORY_PROPERTY_VALUE, DOUBLE_DECIMAL_PLACE_DIGITS);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de totalMemory.");

  rc = az_iot_hub_client_properties_writer_end_component(hub_client, &jw);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo cerrando deviceInformation.");

  rc = az_json_writer_append_end_object(&jw);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo cerrando el objeto JSON.");

  payload_buffer_span = az_json_writer_get_bytes_used_in_destination(&jw);
  if ((payload_buffer_size - az_span_size(payload_buffer_span)) < 1)
  {
    LogError("No cabe el terminador nulo del payload.");
    return RESULT_ERROR;
  }
  payload_buffer[az_span_size(payload_buffer_span)] = null_terminator;
  *payload_buffer_length = az_span_size(payload_buffer_span);

  return RESULT_OK;
}

/* ======================= Propiedades escribibles ======================= */
static int generate_properties_update_response(
  azure_iot_t* azure_iot, az_span nombre, double valor_double, int32_t valor_int,
  bool es_double, int32_t version, uint8_t* buffer, size_t buffer_size, size_t* response_length)
{
  az_result azrc;
  az_json_writer jw;
  az_span response = az_span_create(buffer, buffer_size);

  azrc = az_json_writer_init(&jw, response, NULL);
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo iniciando el acuse de propiedades.");
  azrc = az_json_writer_append_begin_object(&jw);
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo abriendo el acuse de propiedades.");

  azrc = az_iot_hub_client_properties_writer_begin_response_status(
    &azure_iot->iot_hub_client, &jw, nombre, (int32_t)AZ_IOT_STATUS_OK, version,
    AZ_SPAN_FROM_STR(WRITABLE_PROPERTY_RESPONSE_SUCCESS));
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo escribiendo el estado del acuse.");

  if (es_double) { azrc = az_json_writer_append_double(&jw, valor_double, 1); }
  else           { azrc = az_json_writer_append_int32(&jw, valor_int); }
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo escribiendo el valor del acuse.");

  azrc = az_iot_hub_client_properties_writer_end_response_status(&azure_iot->iot_hub_client, &jw);
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo cerrando el estado del acuse.");

  azrc = az_json_writer_append_end_object(&jw);
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo cerrando el acuse de propiedades.");

  *response_length = az_span_size(az_json_writer_get_bytes_used_in_destination(&jw));
  return RESULT_OK;
}

static int consume_properties_and_generate_response(
  azure_iot_t* azure_iot, az_span properties, uint8_t* buffer, size_t buffer_size, size_t* response_length)
{
  int result = RESULT_OK;
  az_json_reader jr;
  az_span component_name;
  int32_t version = 0;

  *response_length = 0;

  az_result azrc = az_json_reader_init(&jr, properties, NULL);
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo iniciando el lector JSON de propiedades.");

  const az_iot_hub_client_properties_message_type message_type =
    AZ_IOT_HUB_CLIENT_PROPERTIES_MESSAGE_TYPE_WRITABLE_UPDATED;

  azrc = az_iot_hub_client_properties_get_properties_version(&azure_iot->iot_hub_client, &jr, message_type, &version);
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo leyendo la version de las propiedades.");

  azrc = az_json_reader_init(&jr, properties, NULL);
  EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo reiniciando el lector JSON.");

  while (az_result_succeeded(
    azrc = az_iot_hub_client_properties_get_next_component_property(
      &azure_iot->iot_hub_client, &jr, message_type, AZ_IOT_HUB_CLIENT_PROPERTY_WRITABLE, &component_name)))
  {
    if (az_json_token_is_text_equal(&jr.token, AZ_SPAN_FROM_STR(WRITABLE_UMBRAL_RIEGO)))
    {
      double valor;
      azrc = az_json_reader_next_token(&jr);
      EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo avanzando al valor de umbralRiegoVWC.");
      azrc = az_json_token_get_double(&jr.token, &valor);
      EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo leyendo umbralRiegoVWC.");

      umbral_riego_vwc = (float)valor;
      LogInfo("Nuevo umbral de riego: %.1f %%VWC", umbral_riego_vwc);

      result = generate_properties_update_response(
        azure_iot, AZ_SPAN_FROM_STR(WRITABLE_UMBRAL_RIEGO), valor, 0, true,
        version, buffer, buffer_size, response_length);
      EXIT_IF_TRUE(result != RESULT_OK, RESULT_ERROR, "Fallo generando el acuse de umbralRiegoVWC.");
    }
    else if (az_json_token_is_text_equal(&jr.token, AZ_SPAN_FROM_STR(WRITABLE_INTERVALO)))
    {
      int32_t valor;
      azrc = az_json_reader_next_token(&jr);
      EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo avanzando al valor de intervaloTelemetriaSeg.");
      azrc = az_json_token_get_int32(&jr.token, &valor);
      EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo leyendo intervaloTelemetriaSeg.");

      if (valor >= 5) { azure_pnp_set_telemetry_frequency((size_t)valor); }

      result = generate_properties_update_response(
        azure_iot, AZ_SPAN_FROM_STR(WRITABLE_INTERVALO), 0, valor, false,
        version, buffer, buffer_size, response_length);
      EXIT_IF_TRUE(result != RESULT_OK, RESULT_ERROR, "Fallo generando el acuse de intervaloTelemetriaSeg.");
    }
    else
    {
      LogError("Propiedad no esperada (%.*s).", az_span_size(jr.token.slice), az_span_ptr(jr.token.slice));
    }

    azrc = az_json_reader_next_token(&jr);
    EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo avanzando al siguiente token.");
    azrc = az_json_reader_skip_children(&jr);
    EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo saltando los hijos del token.");
    azrc = az_json_reader_next_token(&jr);
    EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo avanzando al siguiente token (2).");
  }

  return RESULT_OK;
}
