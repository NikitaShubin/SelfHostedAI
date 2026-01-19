#!/bin/bash
# Скрипт для мониторинга состояния сервисов AI-стека
# Показывает статус контейнеров, доступность Ollama API и прогресс загрузки моделей

# Проверяем, поддерживает ли терминал цвета
if [ -t 1 ]; then
    # Минимальный набор контрастных цветов
    GREEN='\033[1;32m'  # Ярко-зелёный для успеха
    RED='\033[1;31m'    # Ярко-красный для ошибок
    YELLOW='\033[1;33m' # Ярко-жёлтый для предупреждений
    BLUE='\033[1;36m'   # Ярко-голубой для заголовков
    PURPLE='\033[1;35m' # Ярко-фиолетовый для мониторинга
    CYAN='\033[1;34m'   # Ярко-голубой для WebUI
    NC='\033[0m'        # No Color
else
    # Без цветов (например, при перенаправлении вывода в файл)
    GREEN=''
    RED=''
    YELLOW=''
    BLUE=''
    PURPLE=''
    CYAN=''
    NC=''
fi

echo -e "${BLUE}=== Статус сервисов ===${NC}"
echo ""

# 1. Проверка контейнеров через Docker Compose
echo -e "${BLUE}📦 Контейнеры:${NC}"
docker compose ps

echo ""
echo -e "${BLUE}🌐 Доступность:${NC}"

# 2. Проверка Monitoring API (таймаут 5 секунд)
if timeout 5 curl -s http://localhost:5000/api/system-info > /dev/null; then
    echo -e "${PURPLE}✅ Мониторинг: http://localhost:5000${NC}"
else
    echo -e "${RED}❌ Мониторинг не отвечает${NC}"
fi

# 3. Проверка WebUI (таймаут 5 секунд)
if timeout 5 curl -s http://localhost:8080 > /dev/null; then
    echo -e "${CYAN}✅ WebUI: http://localhost:8080${NC}"
else
    echo -e "${RED}❌ WebUI не отвечает${NC}"
fi

# 4. Проверка Ollama API (таймаут 5 секунд)
if timeout 5 curl -s http://localhost:11434/api/tags > /dev/null; then
    echo -e "${GREEN}✅ Ollama API: http://localhost:11434${NC}"
    # Получаем список моделей и извлекаем их названия
    echo "   Модели:"
    curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//;s/^/     - /'
else
    echo -e "${RED}❌ Ollama не отвечает${NC}"
fi

# 5. Проверка скачиваемых прямо сейчас моделей
# Ищем в логах Ollama информацию о загрузке моделей
CURRENT_DOWNLOAD=$(docker compose logs ollama --tail=15 2>/dev/null | grep -E "(pulling|downloading).*(layer|digest|%)" | tail -1)
if [ -n "$CURRENT_DOWNLOAD" ]; then
    echo ""
    echo -e "${YELLOW}🔄 Сейчас загружается:${NC}"
    echo "   $CURRENT_DOWNLOAD" | sed 's/^/   /'
fi