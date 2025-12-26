# Образ Ollama с дополнительными утилитами и скриптом инициализации

FROM ollama/ollama:latest

# Устанавливаем curl и jq для работы скрипта инициализации
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Копируем скрипт инициализации моделей
COPY init-models.sh /init-models.sh
RUN chmod +x /init-models.sh

# Запускаем скрипт инициализации при старте контейнера
ENTRYPOINT ["/init-models.sh"]