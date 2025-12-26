# Образ Ollama с дополнительными утилитами и скриптом инициализации

# hadolint global ignore = DL3007, DL3008  # Не фиксируем версии, т.к. в этом образе нужны свежие пакеты и образы

FROM ollama/ollama:latest

# Устанавливаем curl и jq для работы скрипта инициализации
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Копируем скрипт инициализации моделей
COPY init-models.sh /init-models.sh
RUN chmod +x /init-models.sh

# Запускаем скрипт инициализации при старте контейнера
ENTRYPOINT ["/init-models.sh"]