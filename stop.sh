#!/bin/bash
# Скрипт для остановки всех сервисов AI-стека

# Определяем текущую директорию скрипта
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Остановка AI стека..."
# Останавливаем контейнеры через Docker Compose
docker compose -f "$DIR/docker-compose.yaml" down

echo "Контейнеры остановлены."