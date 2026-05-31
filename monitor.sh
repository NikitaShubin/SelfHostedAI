#!/bin/bash
# Скрипт для мониторинга состояния сервисов AI-стека

cd "$(cd "$(dirname "$0")" && pwd)"

if [ -t 1 ]; then
    GREEN='\033[1;32m'; RED='\033[1;31m'; YELLOW='\033[1;33m'
    BLUE='\033[1;36m'; PURPLE='\033[1;35m'; CYAN='\033[1;34m'
    BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; PURPLE=''; CYAN=''; BOLD=''; DIM=''; NC=''
fi

echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}  Состояние AI стека${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

echo -e "${BOLD}📦 Контейнеры:${NC}"
docker compose ps 2>&1
echo ""

echo -e "${BOLD}🌐 Сервисы:${NC}"

if timeout 5 curl -s http://localhost:5000/api/system-info > /dev/null 2>&1; then
    echo -e "  ${PURPLE}✅${NC} Панель управления  ${BOLD}http://localhost:5000${NC}"
else
    echo -e "  ${RED}❌${NC} Панель управления  ${DIM}недоступна${NC}"
fi

if timeout 5 curl -s http://localhost:8080 > /dev/null 2>&1; then
    echo -e "  ${CYAN}✅${NC} WebUI              ${BOLD}http://localhost:8080${NC}"
else
    echo -e "  ${RED}❌${NC} WebUI              ${DIM}недоступен${NC}"
fi

if timeout 5 curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "  ${GREEN}✅${NC} Ollama API         ${BOLD}http://localhost:11434${NC}"
    MODELS=$(curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//g')
    MODEL_COUNT=$(echo "$MODELS" | grep -c . 2>/dev/null)
    if [ "$MODEL_COUNT" -gt 0 ]; then
        echo -e "     ${DIM}Модели (${MODEL_COUNT}):${NC}"
        echo "$MODELS" | sed 's/^/       • /'
    fi
else
    echo -e "  ${RED}❌${NC} Ollama API         ${DIM}недоступен${NC}"
fi

# Определяем активную загрузку или ошибки загрузки
# Ищем в логах последних 3 минут
LOGS=$(docker logs ollama --since=3m 2>/dev/null)

# Убираем ANSI-коды для grep
CLEAN=$(echo "$LOGS" | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g')

# Проверяем наличие активного pull
PULLING=$(echo "$CLEAN" | grep -E "pulling" | grep -v "pulling manifest" | tail -1)
if [ -z "$PULLING" ]; then
    PULLING=$(echo "$CLEAN" | grep "POST.*/api/pull" | tail -1)
fi

# Проверяем ошибки pull
ERROR=$(echo "$CLEAN" | grep -iE "error|requires.*macOS|manifest.*not found" | tail -3)

# Проверяем активные процессы
ACTIVE_PULL=$(docker exec ollama ps aux 2>/dev/null | grep "ollama pull" | grep -v grep)

if [ -n "$ACTIVE_PULL" ]; then
    echo ""
    echo -e "${YELLOW}🔄 Загружается модель...${NC}"
elif [ -n "$PULLING" ]; then
    # Извлекаем имя модели из POST /api/pull
    MODEL=$(echo "$PULLING" | grep -oP '"/api/pull".*"\\K[^"]+' || echo "")
    if [ -n "$MODEL" ]; then
        echo ""
        echo -e "${YELLOW}🔄 Загружается: ${BOLD}${MODEL}${NC}"
    fi
fi

if [ -n "$ERROR" ]; then
    echo ""
    echo -e "${RED}❌ Ошибки загрузки:${NC}"
    echo "$ERROR" | sed 's/^/   /'
fi
