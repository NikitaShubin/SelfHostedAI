#!/bin/bash
# Скрипт инициализации Ollama: запускает сервер и загружает модели из models.txt

# Путь к файлу models.txt (монтируется из хоста)
MODELS_FILE="/models.txt"

# Функция для извлечения моделей из файла
extract_models() {
    if [ ! -f "$MODELS_FILE" ]; then
        echo "Файл $MODELS_FILE не найден. Создайте его в корне проекта."
        echo "Пример содержимого:"
        echo "# llama3:8b"
        echo "# mistral:7b"
        return 1
    fi

    # Извлекаем активные модели (незакомментированные строки)
    grep -v '^#' "$MODELS_FILE" | grep -v '^$' | sed 's/#.*$//' | xargs
}

# Запускаем Ollama сервер в фоновом режиме
echo "Запуск Ollama сервера..."
ollama serve &
OLLAMA_PID=$!

# Ждём запуска сервера (максимум 60 секунд)
echo "Ожидание запуска сервера Ollama..."
MAX_WAIT=60
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    # Проверяем доступность API
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✓ Сервер Ollama запущен!"
        break
    fi

    echo "Ожидание... ($((WAITED + 2))/60 секунд)"
    sleep 2
    WAITED=$((WAITED + 2))
done

# Проверяем, запустился ли сервер
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✗ Ошибка: Сервер Ollama не запустился за 60 секунд"
    echo "Проверьте логи: docker compose logs ollama"
    kill $OLLAMA_PID 2>/dev/null
    exit 1
fi

# Загружаем модели из файла models.txt
echo ""
echo "Чтение списка моделей из $MODELS_FILE..."
MODELS=$(extract_models)

if [ -z "$MODELS" ]; then
    echo "Не найдено активных моделей для загрузки."
    echo "Раскомментируйте модели в $MODELS_FILE (удалите # в начале строки)"
else
    echo "Найдены модели для загрузки:"
    echo "$MODELS" | tr ' ' '\n' | sed 's/^/  - /'
    echo ""

    # Проверяет, что модель реально присутствует в Ollama
    model_present() {
        local name=$1
        curl -s http://localhost:11434/api/tags 2>/dev/null | \
            jq -e ".models[] | select(.name == \"$name\")" > /dev/null 2>&1
    }

    # Кол-во попыток загрузки одной модели (на случай транзитных сбоев DNS/сети)
    PULL_ATTEMPTS=3

    # Проходим по каждой модели из списка
    for model in $MODELS; do
        echo "Проверяем модель: $model"

        if model_present "$model"; then
            echo "  ✓ Модель '$model' уже загружена"
            echo ""
            continue
        fi

        echo "  Загружаем модель: $model"
        echo "  Это может занять несколько минут в зависимости от размера модели..."

        ATTEMPT=1
        PULL_OK=0
        while [ $ATTEMPT -le $PULL_ATTEMPTS ]; do
            if [ $ATTEMPT -gt 1 ]; then
                echo "    Попытка $ATTEMPT/$PULL_ATTEMPTS (после паузы 10с)..."
                sleep 10
            fi

            # pull в отдельной строке, чтобы любые ошибки дошли до проверки ниже
            if ollama pull "$model" 2>&1 | tee /tmp/ollama_pull.log; then
                : # код конвейера = tee, поэтому полагаемся на проверку наличия модели
            fi

            # Критерий успеха — фактическое наличие модели, а не код конвейера
            if model_present "$model"; then
                PULL_OK=1
                break
            fi

            echo "    ⚠  Не удалось загрузить '$model', код части конвейера мог скрыть ошибку."
            echo "       $(tail -1 /tmp/ollama_pull.log 2>/dev/null)"
            ATTEMPT=$((ATTEMPT + 1))
        done

        if [ "$PULL_OK" = "1" ]; then
            echo "  ✓ Модель '$model' успешно загружена"
        else
            echo "  ✗ Ошибка при загрузке модели '$model' после $PULL_ATTEMPTS попыток"
            echo "    Проверьте название модели, сетевой доступ и DNS"
        fi
        echo ""
    done
fi

echo ""
echo "========================================"
echo "Ollama сервер запущен и готов к работе!"
echo "API доступен на: http://localhost:11434"
echo ""
echo "Для просмотра загруженных моделей:"
echo "  curl http://localhost:11434/api/tags"
echo "========================================"
echo ""

# Ожидаем завершения основного процесса (Ollama сервера)
wait $OLLAMA_PID
