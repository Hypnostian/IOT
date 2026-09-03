# Laboratorio 1: Introducción a Azure IoT Central

## Descripción

Este repositorio contiene el desarrollo y las evidencias del **Laboratorio 1 de IoT + Cloud + Sistemas Distribuidos**, realizado en Azure IoT Central.

El escenario implementado representa un sistema de monitoreo para un **panel solar simulado**. La solución permite visualizar variables eléctricas y térmicas, consultar propiedades del dispositivo, ejecutar un comando remoto y generar una alerta por correo electrónico cuando la temperatura supera el umbral configurado.

## Información académica

- **Universidad:** Universidad Autónoma de Bucaramanga
- **Programa:** Ingeniería de Sistemas
- **Asignatura:** IoT + Cloud + Sistemas Distribuidos
- **Laboratorio:** Introducción a Azure IoT Central
- **Fecha:** Septiembre de 2026

## Integrantes

- Juan Sebastian Lizcano Jaimes
- Angie Katherine Suarez Ortiz

## Objetivos

- Crear una aplicación personalizada en Azure IoT Central.
- Reconocer las secciones principales de una aplicación IoT Central.
- Diferenciar entre aplicación, plantilla de dispositivo y dispositivo concreto.
- Modelar un panel solar mediante telemetrías, propiedades y comandos.
- Crear vistas orientadas al monitoreo por parte de un operador.
- Construir un panel con las variables principales del sistema.
- Configurar y validar una regla de alerta basada en telemetría.
- Identificar ventajas y limitaciones de una plataforma IoT administrada.

## Escenario desarrollado

El escenario representa un panel solar conectado a un controlador IoT. El dispositivo reporta periódicamente información sobre la generación de energía y sus condiciones de operación.

El operador puede utilizar Azure IoT Central para:

- Supervisar la potencia generada.
- Consultar la temperatura del panel.
- Observar el voltaje y la corriente de salida.
- Revisar información descriptiva del dispositivo.
- Ejecutar un comando de reinicio del controlador.
- Recibir una alerta cuando la temperatura supera el umbral configurado.

## Modelo del dispositivo

La plantilla se creó con el nombre **Dispositivo Laboratorio 1**.

### Telemetrías

| Capacidad | Nombre interno | Tipo de dato | Unidad | Descripción |
|---|---|---:|---:|---|
| Potencia generada | `potenciaGenerada` | Double | W | Potencia instantánea producida por el panel. |
| Temperatura del panel | `temperaturaPanel` | Double | °C | Temperatura operativa utilizada para detectar sobrecalentamiento. |
| Voltaje de salida | `voltajeSalida` | Double | V | Voltaje entregado por el sistema. |
| Corriente de salida | `corrienteSalida` | Double | A | Corriente eléctrica generada por el panel. |

### Propiedades

| Propiedad | Nombre interno | Tipo de dato | Descripción |
|---|---|---:|---|
| Ubicación | `ubicacion` | String | Lugar en el que se encuentra instalado el panel. |
| Potencia nominal | `potenciaNominal` | Double | Capacidad nominal de generación del panel. |

### Comando

| Comando | Nombre interno | Descripción |
|---|---|---|
| Reiniciar controlador | `reiniciarControlador` | Representa una acción remota para reiniciar el controlador del dispositivo. |

## Dispositivo simulado

Se creó un dispositivo a partir de la plantilla publicada y se habilitó la opción de simulación de Azure IoT Central.

El dispositivo simulado permitió validar el laboratorio sin utilizar hardware ni desarrollar código adicional. Durante la prueba, el dispositivo apareció conectado y generó datos para todas las telemetrías configuradas.

> **Nota de seguridad:** este repositorio no contiene claves del dispositivo, tokens de API, credenciales, cadenas de conexión ni secretos de aprovisionamiento.

## Vista y panel de monitoreo

Se creó una vista orientada al operador con información sobre el comportamiento del panel solar.

También se construyó un panel de monitoreo con:

- Gráfica de potencia generada.
- Gráfica de temperatura del panel.
- Indicador de voltaje de salida.
- Indicador de corriente de salida.

La organización visual permite consultar rápidamente el estado del sistema sin revisar directamente los datos sin procesar.

## Regla de alerta

Se configuró la regla **Alerta de temperatura alta** con las siguientes características:

- **Plantilla objetivo:** Dispositivo Laboratorio 1.
- **Telemetría:** Temperatura del panel.
- **Operador:** Mayor que.
- **Umbral de prueba:** 25 °C.
- **Acción:** Envío de correo electrónico.
- **Estado:** Habilitada.

El umbral de 25 °C se utilizó para comprobar la regla con los valores generados por el simulador. En un escenario real, el umbral se ajustaría de acuerdo con las especificaciones técnicas y condiciones de operación del panel.

La prueba se consideró satisfactoria porque la telemetría superó el umbral y se recibió el correo electrónico configurado en la acción.

## Resultados

- La aplicación personalizada se creó correctamente.
- La plantilla incluyó telemetrías, propiedades y un comando.
- La plantilla fue publicada antes de crear el dispositivo.
- El dispositivo simulado apareció conectado y transmitió telemetría.
- Las variables se visualizaron en la vista y en el panel.
- El comando quedó disponible para el operador.
- La regla se habilitó y evaluó la temperatura recibida.
- La notificación por correo electrónico fue recibida correctamente.

## Decisiones de modelado

Las variables que cambian continuamente se definieron como **telemetrías**. Por este motivo, potencia, temperatura, voltaje y corriente se reportan periódicamente desde el dispositivo.

La ubicación y la potencia nominal se definieron como **propiedades**, ya que describen características relativamente estables del panel.

El reinicio del controlador se definió como **comando**, porque representa una operación solicitada por el operador desde Azure IoT Central hacia el dispositivo.

## Limitaciones identificadas

- La simulación integrada ofrece un control limitado sobre la secuencia exacta de valores generados.
- Las vistas y paneles dependen de los componentes disponibles en Azure IoT Central.
- Los cambios realizados después de publicar una plantilla pueden afectar reglas, vistas y dispositivos asociados.
- Una implementación con cientos de dispositivos requeriría una estrategia más completa de identidades, permisos, aprovisionamiento y versionamiento.
- El aumento del volumen de telemetría obligaría a evaluar costos, almacenamiento y frecuencia de envío.
- Los análisis avanzados o integraciones especializadas podrían requerir otros servicios de Azure o una arquitectura IoT más flexible.

```

