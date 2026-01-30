#!/bin/bash
# Скрипт для остановки всех сервисов AI-стека

# Переход в папку со скриптом:
cd "$(cd "$(dirname "$0")" && pwd)"

echo "Остановка AI стека..."
# Останавливаем контейнеры через Docker Compose
docker compose -f "./docker-compose.yaml" down

echo "Контейнеры остановлены."