#!/bin/bash
# Основной скрипт запуска AI-стека
# Собирает контейнеры, запускает их и мониторит загрузку моделей

# Переход в папку со скриптом:
cd "$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "Запуск AI стека с Ollama и Open WebUI"
echo "========================================"

# Собираем и запускаем контейнеры в фоновом режиме
echo ""
echo "🚀 Сборка и запуск Docker контейнеров..."
docker compose build
docker compose up -d

# Мониторинг до загрузки всех моделей:
# Подсчитываем количество ожидаемых моделей (незакомментированных строк в models.txt)
EXPECTED=$(grep -v '^#' "./models.txt" 2>/dev/null | grep -v '^$' | sed 's/#.*$//' | wc -l)

# Бесконечный цикл мониторинга
while true; do
    clear  # Очищаем экран
    "./monitor.sh"  # Показываем текущий статус
    echo ""

    # Проверяем доступность Ollama API
    if timeout 5 curl -s http://localhost:11434/api/tags > /dev/null; then
        # Считаем количество загруженных моделей
        LOADED=$(curl -s http://localhost:11434/api/tags | grep -o '"name"' | wc -l)

        # Проверяем, все ли модели загружены
        if [ "$LOADED" -ge "$EXPECTED" ]; then
            echo "✅ Все модели загружены!"
            break  # Выходим из цикла
        else
            echo "📊 $LOADED/$EXPECTED моделей"
            echo "⏳ Ожидание..."
            sleep 5  # Ждём 5 секунд перед следующей проверкой
        fi
    else
        echo "⏳ Запуск..."
        sleep 5  # Ждём 5 секунд если Ollama ещё не запустился
    fi
done