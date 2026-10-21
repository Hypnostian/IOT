# Imagen comun para el publicador, la ingesta y el receptor de alertas (amd64 y arm64).
FROM python:3.12.15-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./
RUN useradd --uid 1000 --no-create-home app
USER app
