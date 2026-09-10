import serial

print("Conectando con el puerto serial de Wokwi...")

ser = serial.serial_for_url(
    "rfc2217://localhost:4000",
    baudrate=115200,
    timeout=1,
)

print("Conectado. Presiona Ctrl+C para terminar.")

try:
    while True:
        line = ser.readline()

        if line:
            print(
                line.decode(
                    "utf-8",
                    errors="replace",
                ).rstrip()
            )

except KeyboardInterrupt:
    print("\nMonitor detenido.")

finally:
    ser.close()