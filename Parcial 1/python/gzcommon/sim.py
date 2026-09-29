# -*- coding: utf-8 -*-
"""
Modelos de señal para los nodos que no tienen hardware físico.

Criterio de diseño: las series se calculan SIEMPRE a partir de la hora de
reloj (no de un contador interno). Así, si un servicio se reinicia o se
desconecta a propósito, al volver retoma la curva donde le corresponde y la
serie no muestra un salto artificial: solo el hueco de la desconexión, que es
justamente lo que el parcial pide evidenciar.

Los rangos operativos están tomados de agronomía del cacao (Theobroma cacao)
y se documentan en la tabla de parámetros del documento del proyecto:

  * Humedad de suelo útil          25 - 35 %VWC   (marchitez por debajo de 20)
  * Temperatura del aire óptima    21 - 32 C
  * Humedad relativa               70 - 85 %
  * Sombra del sombrío             30 - 50 %
  * CE del suelo                   < 2 dS/m (el cacao es sensible a salinidad)
  * Fermentación                   pico de 45 - 50 C entre las 48 y 72 h
  * Grano seco en bodega           HR < 70 %
"""

import hashlib
import math
import random
import time

# Zona horaria del predio: America/Bogota = UTC-5 fijo (Colombia no usa DST).
OFFSET_LOCAL_H = -5.0


def hora_local(ts=None):
    """Hora decimal local del predio (0.0 - 24.0)."""
    ts = ts if ts is not None else time.time()
    return ((ts / 3600.0) + OFFSET_LOCAL_H) % 24.0


def dia_juliano(ts=None):
    ts = ts if ts is not None else time.time()
    return int((ts / 86400.0) + (OFFSET_LOCAL_H / 24.0))


def _semilla(nombre, periodo=0):
    """Semilla estable por nombre y periodo, para que el ruido sea repetible."""
    h = hashlib.md5("{}:{}".format(nombre, periodo).encode()).hexdigest()
    return int(h[:8], 16)


def ruido(nombre, amplitud, periodo_s=300, ts=None):
    """
    Ruido suave: interpola entre dos valores aleatorios estables por tramo,
    de modo que la serie no salta de una muestra a la siguiente.
    """
    ts = ts if ts is not None else time.time()
    tramo = int(ts // periodo_s)
    frac = (ts % periodo_s) / float(periodo_s)
    a = random.Random(_semilla(nombre, tramo)).uniform(-1, 1)
    b = random.Random(_semilla(nombre, tramo + 1)).uniform(-1, 1)
    # Interpolación con suavizado coseno.
    s = (1 - math.cos(frac * math.pi)) / 2.0
    return (a + (b - a) * s) * amplitud


def curva_diurna(ts=None, hora_pico=14.0):
    """
    Curva 0..1 con forma de día: 0 de noche, máximo a `hora_pico`.
    Se usa para radiación, PAR y el componente solar de la temperatura.
    """
    h = hora_local(ts)
    # Amanece ~06:00 y anochece ~18:15 en Santander todo el año.
    amanecer, atardecer = 5.9, 18.2
    if h < amanecer or h > atardecer:
        return 0.0
    fase = (h - amanecer) / (atardecer - amanecer)
    return max(0.0, math.sin(fase * math.pi))


def nubosidad(ts=None):
    """Factor 0.25 - 1.0 que simula el paso de nubes sobre el predio."""
    return 0.25 + 0.75 * (0.5 + 0.5 * ruido("nubes", 1.0, 1800, ts))


def evento_lluvia(ts=None, nombre="lluvia"):
    """
    Lluvia convectiva de tarde, típica del piedemonte santandereano.
    Devuelve mm en el intervalo de muestreo (0 la mayor parte del tiempo).
    """
    ts = ts if ts is not None else time.time()
    h = hora_local(ts)
    dia = dia_juliano(ts)
    rnd = random.Random(_semilla(nombre, dia))

    total = 0.0

    # 1) Aguacero convectivo de la tarde: ocurre algo más de la mitad de los
    #    días y aporta la mayor parte del acumulado anual (~2200 mm/año, que
    #    es lo que registra la zona de San Vicente de Chucurí).
    if rnd.random() < 0.55:
        inicio = rnd.uniform(13.0, 17.0)
        duracion = rnd.uniform(0.5, 2.5)
        if inicio <= h <= inicio + duracion:
            intensidad = rnd.uniform(2.0, 18.0)  # mm/h
            total += intensidad * math.sin(((h - inicio) / duracion) * math.pi)

    # 2) Llovizna de madrugada: aporta poco volumen pero moja la hoja durante
    #    horas, y es la que dispara el riesgo de monilia. Por eso se modela
    #    aparte del aguacero.
    if rnd.random() < 0.45:
        inicio_ll = rnd.uniform(4.0, 7.0)
        duracion_ll = rnd.uniform(0.5, 1.5)
        if inicio_ll <= h <= inicio_ll + duracion_ll:
            intensidad_ll = rnd.uniform(0.5, 3.0)
            total += intensidad_ll * math.sin(
                ((h - inicio_ll) / duracion_ll) * math.pi)

    return max(0.0, total)


# --------------------------------------------------------------------------
# Nodo de suelo (dev01, dev02, dev03)
# --------------------------------------------------------------------------
def nodo_suelo(nombre, ts=None, base_vwc=30.0, base_ce=1.1):
    ts = ts if ts is not None else time.time()
    sol = curva_diurna(ts) * nubosidad(ts)
    lluvia = evento_lluvia(ts, nombre + "-lluvia")

    # El suelo se seca durante el día y se recarga con la lluvia.
    ciclo_secado = -2.6 * sol
    recarga = min(9.0, lluvia * 0.85)
    humedad = base_vwc + ciclo_secado + recarga + ruido(nombre + "-vwc", 2.2, 900, ts)
    humedad = max(12.0, min(48.0, humedad))

    # Temperatura del suelo a 20 cm: amortiguada y retrasada ~3 h respecto del aire.
    sol_retrasado = curva_diurna(ts - 3 * 3600) * nubosidad(ts - 3 * 3600)
    temp_suelo = 22.4 + 3.1 * sol_retrasado + ruido(nombre + "-ts", 0.5, 1800, ts)

    # La CE sube cuando el suelo se seca (las sales se concentran).
    ce = base_ce + (30.0 - humedad) * 0.035 + ruido(nombre + "-ce", 0.08, 1200, ts)
    ce = max(0.15, min(4.5, ce))

    # Canopy: sigue al aire pero con calentamiento radiativo al sol.
    temp_canopy = 21.0 + 9.5 * sol + ruido(nombre + "-tc", 0.9, 900, ts)

    # PAR bajo sombrío: 35 - 60 % del PAR a cielo abierto.
    par = 1850.0 * sol * (0.40 + 0.18 * (0.5 + 0.5 * ruido(nombre + "-par", 1.0, 600, ts)))
    par = max(0.0, par)

    return {
        "humedadSuelo": round(humedad, 1),
        "tempSuelo": round(temp_suelo, 1),
        "ceSuelo": round(ce, 2),
        "tempCanopy": round(temp_canopy, 1),
        "parPPFD": round(par, 0),
        "bateria": bateria(nombre, ts),
        "rssi": int(-72 + ruido(nombre + "-rssi", 12, 600, ts)),
    }


def bateria(nombre, ts=None, minimo=62):
    """Batería con panel solar: se recarga de día y se descarga de noche."""
    ts = ts if ts is not None else time.time()
    sol = curva_diurna(ts)
    nivel = minimo + 30 * sol + 6 * (0.5 + 0.5 * ruido(nombre + "-bat", 1.0, 7200, ts))
    return int(max(5, min(100, nivel)))


# --------------------------------------------------------------------------
# Nodo de dosel (dev04)
# --------------------------------------------------------------------------
def nodo_dosel(nombre, ts=None):
    ts = ts if ts is not None else time.time()
    sol = curva_diurna(ts)
    nub = nubosidad(ts)
    lluvia = evento_lluvia(ts, "estacion-lluvia")

    temp = 20.2 + 8.8 * sol * nub + ruido(nombre + "-t", 0.7, 900, ts)
    if lluvia > 0:
        temp -= 1.8

    hr = 94.0 - 26.0 * sol * nub + ruido(nombre + "-h", 3.0, 900, ts)
    if lluvia > 0:
        hr = min(99.0, hr + 6.0)
    hr = max(40.0, min(99.5, hr))

    lux_abierto = 105000.0 * sol * nub
    # Transmisión del sombrío: 0.40 - 0.72, es decir un índice de sombra de
    # 28 % a 60 %. La banda agronómica del cacao es 30 - 50 %, así que la serie
    # la cruza por arriba y por abajo y la regla R09 (sombra < 30 %) se dispara
    # de vez en cuando, que es lo que debe pasar con una alerta real.
    transmision = 0.40 + 0.32 * (0.5 + 0.5 * ruido(nombre + "-tr", 1.0, 3600, ts))
    lux = lux_abierto * transmision
    sombra = (1.0 - transmision) * 100.0

    # Déficit de presión de vapor (Tetens): indicador de estrés del cultivo.
    es = 0.6108 * math.exp((17.27 * temp) / (temp + 237.3))
    dpv = es * (1.0 - hr / 100.0)

    return {
        "tempDosel": round(temp, 1),
        "hrDosel": round(hr, 1),
        "luxDosel": round(lux, 0),
        "indiceSombra": round(sombra, 1),
        "dpvDosel": round(max(0.0, dpv), 2),
        "bateria": bateria(nombre, ts, 70),
    }


# --------------------------------------------------------------------------
# Estación de campo (dev05) - también alimenta el CSV histórico
# --------------------------------------------------------------------------
def estacion_campo(nombre, ts=None, horas_previas=0.0):
    ts = ts if ts is not None else time.time()
    sol = curva_diurna(ts)
    lluvia = evento_lluvia(ts, "estacion-lluvia")
    h = hora_local(ts)

    # La hoja se moja con la lluvia y con el rocío de la madrugada. El rocío no
    # desaparece de golpe al amanecer: se evapora entre las 07:00 y las 09:30, y
    # precisamente en esa franja la hoja ya está a 23-25 C. Esa coincidencia de
    # hoja mojada y temperatura de infección es la ventana crítica de la monilia,
    # así que el modelo tiene que reproducirla.
    if h < 7.0:
        rocio = 1.0
    elif h < 9.5:
        rocio = max(0.0, 1.0 - (h - 7.0) / 2.5)
    elif h > 19.5:
        rocio = min(1.0, (h - 19.5) / 1.5)
    else:
        rocio = 0.0

    humectacion = 18.0 + 58.0 * rocio + 34.0 * min(1.0, lluvia / 6.0)
    humectacion += ruido(nombre + "-hf", 5.0, 900, ts)
    humectacion = max(0.0, min(100.0, humectacion))

    temp_foliar = 20.6 + 8.2 * sol + ruido(nombre + "-tf", 0.8, 900, ts)

    # Riesgo de monilia (Moniliophthora roreri): pesa la humectación presente y
    # las horas acumuladas de hoja mojada, y todo ello se escala por lo cerca
    # que esté la hoja del rango de infección de 22 a 26 C.
    factor_t = max(0.0, 1.0 - abs(temp_foliar - 24.0) / 6.0)
    riesgo = int(max(0, min(100,
        (0.60 * humectacion + 4.0 * min(horas_previas, 12.0)) * factor_t)))

    return {
        "lluviaLote": round(lluvia, 1),
        "humedadFoliar": round(humectacion, 1),
        "horasHumectacion": round(min(24.0, horas_previas), 2),
        "tempFoliar": round(temp_foliar, 1),
        "riesgoMonilia": riesgo,
        "bateria": bateria(nombre, ts, 58),
    }


# --------------------------------------------------------------------------
# Reservorio y riego (dev09)
# --------------------------------------------------------------------------
def reservorio(nombre, ts=None, capacidad_m3=48.0):
    ts = ts if ts is not None else time.time()
    h = hora_local(ts)
    lluvia = evento_lluvia(ts, "estacion-lluvia")

    # Se riega en dos ventanas: 05:30-07:00 y 17:00-18:30.
    regando = (5.5 <= h <= 7.0) or (17.0 <= h <= 18.5)
    # Si acaba de llover no se riega: lógica real de ahorro de agua.
    if lluvia > 3.0:
        regando = False

    caudal = 0.0
    presion = 0.6 + ruido(nombre + "-p0", 0.05, 600, ts)
    if regando:
        caudal = 118.0 + ruido(nombre + "-q", 9.0, 300, ts)
        presion = 3.4 + ruido(nombre + "-p", 0.25, 300, ts)

    # Nivel: baja con el riego y sube con la lluvia que capta el reservorio.
    ciclo = math.cos((h / 24.0) * 2 * math.pi)
    nivel = 68.0 + 14.0 * ciclo + min(16.0, lluvia * 1.4)
    nivel += ruido(nombre + "-n", 2.0, 1800, ts)
    nivel = max(8.0, min(100.0, nivel))

    return {
        "nivelTanque": round(nivel, 1),
        "volumenTanque": round(capacidad_m3 * nivel / 100.0, 2),
        "caudal": round(max(0.0, caudal), 1),
        "presionLinea": round(max(0.0, presion), 2),
        "bombaOn": bool(regando),
    }


# --------------------------------------------------------------------------
# Perímetro y bodega (dev10)
# --------------------------------------------------------------------------
def perimetro(nombre, ts=None):
    ts = ts if ts is not None else time.time()
    h = hora_local(ts)
    sol = curva_diurna(ts)

    # Actividad de los trabajadores: jornada de 06:00 a 17:00.
    jornada = 6.0 <= h <= 17.0
    p_movimiento = 0.42 if jornada else 0.04
    p_puerta = 0.18 if jornada else 0.01

    rnd = random.Random(_semilla(nombre, int(ts // 30)))
    movimiento = rnd.random() < p_movimiento
    puerta = rnd.random() < p_puerta

    temp = 21.5 + 6.4 * sol + ruido(nombre + "-t", 0.6, 1200, ts)
    # La bodega de grano seco debe mantenerse por debajo de 70 % HR.
    hr = 63.0 - 9.0 * sol + ruido(nombre + "-h", 4.0, 1200, ts)

    return {
        "puertaAbierta": bool(puerta),
        "movimiento": bool(movimiento),
        "tempBodega": round(temp, 1),
        "hrBodega": round(max(25.0, min(95.0, hr)), 1),
        "nivelBateriaRespaldo": int(max(40, min(100, 88 + ruido(nombre + "-b", 9, 7200, ts)))),
    }


# --------------------------------------------------------------------------
# Secado y fermentación (dev08) - respaldo por si Wokwi no está corriendo
# --------------------------------------------------------------------------
def secado_fermentacion(nombre, ts=None, inicio_lote=None):
    """
    Ciclo real de fermentación de cacao: 6 días (144 h).
    La masa arranca a temperatura ambiente, sube a 45-50 C entre las 48 y 72 h
    (fase acética) y luego desciende. El pH de la pulpa sube de 3.5 a ~4.8.
    """
    ts = ts if ts is not None else time.time()
    inicio_lote = inicio_lote or (ts - (ts % (6 * 86400)))
    horas = max(0.0, (ts - inicio_lote) / 3600.0) % 144.0

    # Perfil térmico de la fermentación.
    if horas < 24:
        pico = 24.0 + (horas / 24.0) * 12.0
    elif horas < 72:
        pico = 36.0 + 12.5 * math.sin(((horas - 24) / 48.0) * math.pi)
    else:
        pico = 48.5 - (horas - 72) * 0.21

    temp_nucleo = pico + ruido(nombre + "-tn", 0.6, 1800, ts)
    temp_caja = temp_nucleo - 5.5 + 2.0 * curva_diurna(ts) + ruido(nombre + "-tc", 0.5, 900, ts)
    hr_caja = 88.0 - 14.0 * curva_diurna(ts) + ruido(nombre + "-hc", 2.5, 900, ts)

    # La masa pierde agua: de 320 kg de baba a ~128 kg de grano seco.
    masa = 320.0 - (horas / 144.0) * 192.0 + ruido(nombre + "-m", 1.5, 3600, ts)
    ph = 3.45 + (horas / 144.0) * 1.45 + ruido(nombre + "-ph", 0.05, 1800, ts)

    return {
        "tempCaja": round(temp_caja, 1),
        "tempNucleoMasa": round(temp_nucleo, 1),
        "hrCaja": round(max(35.0, min(99.0, hr_caja)), 1),
        "masaEstimada": round(max(0.0, masa), 1),
        "phPulpa": round(ph, 2),
        "horasFermentacion": round(horas, 1),
        "ventiladorOn": bool(temp_caja > 46.0),
    }
