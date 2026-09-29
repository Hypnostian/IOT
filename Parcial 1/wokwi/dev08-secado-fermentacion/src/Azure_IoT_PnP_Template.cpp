// Granja Zenon - Cacao | Parcial 1
// DEV08 - Secado y fermentacion "Marinela"
//
// Origen de envio : Wokwi ESP32 #2 (segunda instancia, firmware DISTINTO al DEV01)
// Plantilla       : GZ Secado y Fermentacion (dtmi:granjazenon:cacao:SecadoFermentacion;1)
// Intervalo       : 20 s
//
// Sensores y actuadores del cajon (ver diagram.json):
//   GPIO 15  DHT22          -> temperatura y HR del cajon    (Aosong AM2302)
//   GPIO 34  NTC            -> temperatura del nucleo de la masa (Maxim DS18B20)
//   GPIO 35  potenciometro  -> masa estimada del lote        (celda 500 kg + HX711)
//   GPIO 32  potenciometro  -> pH de la pulpa                (Atlas Scientific pH)
//   GPIO 13  servo          -> brazo volteador de la masa    (comando VoltearMasa)
//   GPIO  2  LED            -> ventilador de la marquesina   (comando ControlarVentilador)
//
// Proceso real que se controla
// ----------------------------
// La fermentacion del cacao dura entre 5 y 6 dias. La masa arranca a
// temperatura ambiente, sube hasta 45-50 C entre las 48 y 72 h (fase acetica)
// y despues baja. El pH de la pulpa sube de ~3.5 a ~4.8. Si la temperatura
// pasa de 50 C el grano se sobrefermenta y pierde precio; por debajo de 40 C
// a las 48 h la fermentacion se detiene. Esos dos umbrales son las Rules.
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
#include <ESP32Servo.h>
#include "iot_configs.h"

/* --- Identidad del modelo --- */
#define AZURE_PNP_MODEL_ID "dtmi:granjazenon:cacao:SecadoFermentacion;1"

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
#define SAMPLE_MODEL_PROPERTY_VALUE                    "GZ-FermentBox ESP32 v1"
#define SAMPLE_VERSION_PROPERTY_VALUE                  "1.0.0"
#define SAMPLE_OS_NAME_PROPERTY_VALUE                  "FreeRTOS"
#define SAMPLE_ARCHITECTURE_PROPERTY_VALUE             "ESP32-WROOM-32"
#define SAMPLE_PROCESSOR_MANUFACTURER_PROPERTY_VALUE   "ESPRESSIF"
#define SAMPLE_TOTAL_STORAGE_PROPERTY_VALUE            4096
#define SAMPLE_TOTAL_MEMORY_PROPERTY_VALUE             8192

/* --- Telemetria (los nombres deben coincidir con el DTDL) --- */
#define TELEMETRY_TEMP_CAJA         "tempCaja"
#define TELEMETRY_TEMP_NUCLEO       "tempNucleoMasa"
#define TELEMETRY_HR_CAJA           "hrCaja"
#define TELEMETRY_MASA              "masaEstimada"
#define TELEMETRY_PH                "phPulpa"
#define TELEMETRY_HORAS             "horasFermentacion"
#define TELEMETRY_VENTILADOR        "ventiladorOn"

/* --- Propiedades reportadas --- */
#define PROP_NUMERO_CAJA            "numeroCaja"
#define PROP_LOTE_ORIGEN            "loteOrigen"
#define PROP_NUMERO_CAJA_VALOR      3
#define PROP_LOTE_ORIGEN_VALOR      "Lote 1 - Zenon Alto"

/* --- Propiedades escribibles --- */
#define WRITABLE_TEMP_OBJETIVO      "tempObjetivoC"
#define WRITABLE_HORAS_OBJETIVO     "horasObjetivo"
#define WRITABLE_PROPERTY_RESPONSE_SUCCESS  "success"

/* --- Comandos --- */
static az_span COMMAND_VOLTEAR    = AZ_SPAN_FROM_STR("VoltearMasa");
static az_span COMMAND_VENTILADOR = AZ_SPAN_FROM_STR("ControlarVentilador");
#define COMMAND_RESPONSE_CODE_ACCEPTED   200
#define COMMAND_RESPONSE_CODE_REJECTED   404

/* --- Pines --- */
#define PIN_TEMP_NUCLEO    34
#define PIN_MASA           35
#define PIN_PH             32
#define PIN_SERVO          13
#define PIN_VENTILADOR      2

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

static bool ventilador_on = false;
static float temp_objetivo_c = 48.0f;
static float horas_objetivo = 144.0f;   // 6 dias de fermentacion
static uint32_t volteos = 0;

static DHT dht(DHT_PIN, DHT_TYPE);
static Servo servo_volteador;

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
  pinMode(PIN_TEMP_NUCLEO, INPUT);
  pinMode(PIN_MASA, INPUT);
  pinMode(PIN_PH, INPUT);
  pinMode(PIN_VENTILADOR, OUTPUT);
  digitalWrite(PIN_VENTILADOR, LOW);
  analogReadResolution(12);

  servo_volteador.setPeriodHertz(50);
  servo_volteador.attach(PIN_SERVO, 500, 2400);
  servo_volteador.write(0);

  LogInfo("Cajon de fermentacion inicializado (caja 3).");
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

  if (az_span_is_content_equal(command.command_name, COMMAND_VOLTEAR))
  {
    // El brazo barre de 0 a 180 grados y vuelve: un volteo completo de la masa.
    volteos++;
    LogInfo("COMANDO VoltearMasa: iniciando volteo numero %u.", volteos);
    for (int angulo = 0; angulo <= 180; angulo += 15)
    {
      servo_volteador.write(angulo);
      delay(60);
    }
    for (int angulo = 180; angulo >= 0; angulo -= 15)
    {
      servo_volteador.write(angulo);
      delay(60);
    }
    LogInfo("Volteo terminado. La masa se oxigena y baja 2-3 C.");
    response_code = COMMAND_RESPONSE_CODE_ACCEPTED;
  }
  else if (az_span_is_content_equal(command.command_name, COMMAND_VENTILADOR))
  {
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
      ventilador_on = encender;
      digitalWrite(PIN_VENTILADOR, ventilador_on ? HIGH : LOW);
      LogInfo("COMANDO ControlarVentilador: ventilador %s.",
              ventilador_on ? "ENCENDIDO" : "APAGADO");
      response_code = COMMAND_RESPONSE_CODE_ACCEPTED;
    }
    else
    {
      LogError("ControlarVentilador recibio un payload no valido.");
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

/* ================= Modelo temporal del proceso ====================== */
/*
 * Por que el firmware calcula la curva y no se limita a leer el sensor
 * -------------------------------------------------------------------
 * Los componentes de Wokwi son ESTATICOS: el DHT22 devuelve siempre la
 * temperatura fijada en diagram.json, el NTC siempre la suya, y los
 * potenciometros se quedan donde se dejen. Si el firmware se limitara a
 * leerlos, la serie en IoT Central seria una linea plana, que no sirve ni
 * para la ventana de 4 dias ni para demostrar nada.
 *
 * Asi que el nodo hace lo mismo que los de Python: reproduce el proceso
 * real a partir del RELOJ, y usa los sensores como AJUSTE MANUAL encima de
 * esa curva. Durante la sustentacion, mover un potenciometro sigue teniendo
 * efecto visible e inmediato, pero si nadie toca nada la serie evoluciona
 * sola, que es lo que hace un cajon de fermentacion de verdad.
 *
 * La curva se ancla a un epoch absoluto (no al arranque del firmware) para
 * que sea continua aunque el simulador se reinicie: lo unico que se ve en
 * la grafica tras un reinicio es el hueco de la desconexion.
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

// Horas dentro del ciclo de fermentacion (6 dias = 144 h).
static float horas_del_ciclo(time_t ahora)
{
  if (ahora == INDEFINITE_TIME) { return 0.0f; }
  const long ciclo = 144L * 3600L;
  return (float)(ahora % ciclo) / 3600.0f;
}

/*
 * Perfil termico real de la fermentacion del cacao:
 *   0-24 h   fase alcoholica, la masa sube de 24 a 36 C
 *   24-72 h  fase acetica, pico de 45-50 C entre las 48 y 72 h
 *   72-144 h descenso lento hasta el secado
 * Por encima de 50 C el grano se sobrefermenta y pierde precio: ese es el
 * umbral de la regla R06.
 */
static float perfil_nucleo(float horas)
{
  if (horas < 24.0f)
  {
    return 24.0f + (horas / 24.0f) * 12.0f;
  }
  else if (horas < 72.0f)
  {
    return 36.0f + 12.5f * sinf(((horas - 24.0f) / 48.0f) * PI);
  }
  return 48.5f - (horas - 72.0f) * 0.21f;
}

// Ajuste manual de un potenciometro: -1.0 a +1.0 con el centro en reposo.
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

// Temperatura del nucleo: la curva del proceso, mas el NTC como ajuste fino.
// En el cajon real es una sonda DS18B20 clavada en el centro de la masa.
static float leer_temp_nucleo(float horas, time_t ahora)
{
  float tc = perfil_nucleo(horas);

  // El NTC desplaza la curva: a 46 C (su valor en reposo) no la altera.
  const int lectura = analogRead(PIN_TEMP_NUCLEO);
  const float v = (lectura / 4095.0f) * 3.3f;
  if (v > 0.01f && v < 3.29f)
  {
    const float r_ntc = 10000.0f * (v / (3.3f - v));
    const float tk = 1.0f / ((1.0f / 298.15f) +
                             (1.0f / 3950.0f) * logf(r_ntc / 10000.0f));
    tc += ((tk - 273.15f) - 46.0f) * 0.6f;
  }

  tc += ruido(1, ahora, 0.55f);

  // El ventilador extrae calor: baja el nucleo entre 1 y 2 C.
  if (ventilador_on) { tc -= 1.6f; }
  return tc;
}

// Celda de carga de 500 kg. El lote arranca con 320 kg de baba y termina en
// unos 128 kg de grano seco: pierde el 60 % de su peso en agua.
static float leer_masa(float horas, time_t ahora)
{
  float kg = 320.0f - (horas / 144.0f) * 192.0f;
  kg += ajuste_pot(PIN_MASA) * 60.0f;   // +/-30 kg de ajuste manual
  kg += ruido(4, ahora, 1.6f);          // deriva de la celda de carga
  if (kg < 0.0f) { kg = 0.0f; }
  return kg;
}

// Sonda de pH. La pulpa sube de 3.45 a 4.90 a lo largo de la fermentacion.
static float leer_ph(float horas, time_t ahora)
{
  float ph = 3.45f + (horas / 144.0f) * 1.45f;
  ph += ajuste_pot(PIN_PH) * 1.0f;      // +/-0.5 de ajuste manual
  ph += ruido(5, ahora, 0.05f);         // ruido de la sonda de pH
  if (ph < 2.5f) { ph = 2.5f; }
  if (ph > 7.5f) { ph = 7.5f; }
  return ph;
}

/* ======================= Payload de telemetria ======================= */
static int generate_telemetry_payload(uint8_t* payload_buffer, size_t payload_buffer_size, size_t* payload_buffer_length)
{
  az_json_writer jw;
  az_result rc;
  az_span payload_buffer_span = az_span_create(payload_buffer, payload_buffer_size);

  const time_t ahora = time(NULL);
  const float horas = horas_del_ciclo(ahora);
  const float sol = curva_solar(ahora);

  const float temp_nucleo = leer_temp_nucleo(horas, ahora);
  const float masa        = leer_masa(horas, ahora);
  const float ph          = leer_ph(horas, ahora);

  // El cajon esta unos 5,5 C por debajo del nucleo y sigue el ciclo diurno.
  // El DHT22 entra como ajuste manual: en su valor de reposo no altera nada.
  float temp_caja = temp_nucleo - 5.5f + 2.0f * sol + ruido(2, ahora, 0.5f);
  float hr_caja   = 88.0f - 14.0f * sol + ruido(3, ahora, 2.5f);

  const float dht_t = dht.readTemperature();
  const float dht_h = dht.readHumidity();
  if (!isnan(dht_t)) { temp_caja += (dht_t - 34.0f) * 0.5f; }
  if (!isnan(dht_h)) { hr_caja   += (dht_h - 88.0f) * 0.5f; }

  if (hr_caja < 35.0f) { hr_caja = 35.0f; }
  if (hr_caja > 99.0f) { hr_caja = 99.0f; }

  // Control local: si el nucleo pasa del objetivo, entra el ventilador.
  if (temp_nucleo > temp_objetivo_c && !ventilador_on)
  {
    ventilador_on = true;
    digitalWrite(PIN_VENTILADOR, HIGH);
    LogInfo("Control local: nucleo a %.1f C (objetivo %.1f). Ventilador ENCENDIDO.",
            temp_nucleo, temp_objetivo_c);
  }
  else if (temp_nucleo < (temp_objetivo_c - 3.0f) && ventilador_on)
  {
    ventilador_on = false;
    digitalWrite(PIN_VENTILADOR, LOW);
    LogInfo("Control local: nucleo a %.1f C. Ventilador APAGADO.", temp_nucleo);
  }

  rc = az_json_writer_init(&jw, payload_buffer_span, NULL);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo iniciando el escritor JSON.");
  rc = az_json_writer_append_begin_object(&jw);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo abriendo el objeto JSON.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_TEMP_CAJA));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con tempCaja.");
  rc = az_json_writer_append_double(&jw, temp_caja, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de tempCaja.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_TEMP_NUCLEO));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con tempNucleoMasa.");
  rc = az_json_writer_append_double(&jw, temp_nucleo, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de tempNucleoMasa.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_HR_CAJA));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con hrCaja.");
  rc = az_json_writer_append_double(&jw, hr_caja, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de hrCaja.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_MASA));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con masaEstimada.");
  rc = az_json_writer_append_double(&jw, masa, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de masaEstimada.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_PH));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con phPulpa.");
  rc = az_json_writer_append_double(&jw, ph, 2);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de phPulpa.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_HORAS));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con horasFermentacion.");
  rc = az_json_writer_append_double(&jw, horas, 1);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de horasFermentacion.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(TELEMETRY_VENTILADOR));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con ventiladorOn.");
  rc = az_json_writer_append_bool(&jw, ventilador_on);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de ventiladorOn.");

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

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(PROP_NUMERO_CAJA));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con numeroCaja.");
  rc = az_json_writer_append_int32(&jw, PROP_NUMERO_CAJA_VALOR);
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de numeroCaja.");

  rc = az_json_writer_append_property_name(&jw, AZ_SPAN_FROM_STR(PROP_LOTE_ORIGEN));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con loteOrigen.");
  rc = az_json_writer_append_string(&jw, AZ_SPAN_FROM_STR(PROP_LOTE_ORIGEN_VALOR));
  EXIT_IF_AZ_FAILED(rc, RESULT_ERROR, "Fallo con el valor de loteOrigen.");

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
  azure_iot_t* azure_iot, az_span nombre, double valor, int32_t version,
  uint8_t* buffer, size_t buffer_size, size_t* response_length)
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

  azrc = az_json_writer_append_double(&jw, valor, 1);
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
    bool reconocida = false;
    az_span nombre = AZ_SPAN_EMPTY;
    double valor = 0.0;

    if (az_json_token_is_text_equal(&jr.token, AZ_SPAN_FROM_STR(WRITABLE_TEMP_OBJETIVO)))
    {
      nombre = AZ_SPAN_FROM_STR(WRITABLE_TEMP_OBJETIVO);
      reconocida = true;
    }
    else if (az_json_token_is_text_equal(&jr.token, AZ_SPAN_FROM_STR(WRITABLE_HORAS_OBJETIVO)))
    {
      nombre = AZ_SPAN_FROM_STR(WRITABLE_HORAS_OBJETIVO);
      reconocida = true;
    }

    if (reconocida)
    {
      azrc = az_json_reader_next_token(&jr);
      EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo avanzando al valor de la propiedad.");
      azrc = az_json_token_get_double(&jr.token, &valor);
      EXIT_IF_AZ_FAILED(azrc, RESULT_ERROR, "Fallo leyendo el valor de la propiedad.");

      if (az_span_is_content_equal(nombre, AZ_SPAN_FROM_STR(WRITABLE_TEMP_OBJETIVO)))
      {
        temp_objetivo_c = (float)valor;
        LogInfo("Nueva temperatura objetivo del cajon: %.1f C", temp_objetivo_c);
      }
      else
      {
        horas_objetivo = (float)valor;
        LogInfo("Nuevas horas objetivo de fermentacion: %.1f h", horas_objetivo);
      }

      result = generate_properties_update_response(
        azure_iot, nombre, valor, version, buffer, buffer_size, response_length);
      EXIT_IF_TRUE(result != RESULT_OK, RESULT_ERROR, "Fallo generando el acuse de la propiedad.");
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
