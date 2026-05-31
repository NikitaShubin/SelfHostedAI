#!/bin/bash
# Основной скрипт запуска AI-стека
# Собирает контейнеры, запускает их и мониторит загрузку моделей

cd "$(cd "$(dirname "$0")" && pwd)"

if [ -t 1 ]; then
    GREEN='\033[1;32m'; RED='\033[1;31m'; YELLOW='\033[1;33m'
    BLUE='\033[1;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; BOLD=''; DIM=''; NC=''
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}  Запуск AI стека${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

echo -e "${BOLD}🚀 Сборка и запуск контейнеров...${NC}"
docker compose build 2>&1 | sed 's/^/   /'
docker compose up -d 2>&1 | sed 's/^/   /'
echo ""

# Подсчитываем ожидаемые модели
EXPECTED=$(grep -v '^#' "./models.txt" 2>/dev/null | grep -v '^$' | sed 's/#.*$//' | wc -l)
echo -e "${DIM}Ожидается моделей:${NC} ${BOLD}${EXPECTED}${NC}"

# Ждём запуска основных сервисов (до 60 секунд)
echo ""
echo -e "${DIM}⏳ Ожидание запуска сервисов...${NC}"

WAIT_START=$(date +%s)
TIMEOUT=60

# Ждём Ollama
echo -ne "  ${DIM}Ollama...${NC}"
while true; do
    if timeout 3 curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "\r  ${GREEN}✅ Ollama${NC}"
        break
    fi
    elapsed=$(( $(date +%s) - WAIT_START ))
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo -e "\r  ${RED}❌ Ollama (таймаут ${TIMEOUT}с)${NC}"
        echo "Проверьте: docker compose logs ollama"
        exit 1
    fi
    echo -n "."
    sleep 2
done

# Ждём Dashboard
echo -ne "  ${DIM}Панель управления...${NC}"
while true; do
    if timeout 3 curl -s http://localhost:5000/api/system-info > /dev/null 2>&1; then
        echo -e "\r  ${PURPLE}✅ Панель управления${NC}"
        break
    fi
    elapsed=$(( $(date +%s) - WAIT_START ))
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo -e "\r  ${RED}❌ Панель управления (таймаут ${TIMEOUT}с)${NC}"
        echo "Проверьте: docker compose logs dashboard"
        exit 1
    fi
    echo -n "."
    sleep 2
done

echo -e "${GREEN}✅ Сервисы запущены${NC}"
echo ""

# Засекаем начало загрузки моделей
wait_start=$(date +%s)
LOAD_TIMEOUT=600  # 10 минут максимум на загрузку

while true; do
    clear

    elapsed=$(( $(date +%s) - wait_start ))
    mins=$(( elapsed / 60 ))
    secs=$(( elapsed % 60 ))
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Загрузка моделей — прошло ${mins}м ${secs}с${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo ""

    "./monitor.sh"
    echo ""

    # Проверяем таймаут
    if [ "$elapsed" -ge "$LOAD_TIMEOUT" ]; then
        echo -e "${RED}════════════════════════════════════════${NC}"
        echo -e "${RED}  ❌ Таймаут загрузки (${LOAD_TIMEOUT}с)${NC}"
        echo -e "${RED}  Не все модели загрузились${NC}"
        echo -e "${RED}  Проверьте: docker compose logs ollama${NC}"
        echo -e "${RED}════════════════════════════════════════${NC}"
        break
    fi

    LOADED=$(curl -s http://localhost:11434/api/tags | grep -o '"name"' | wc -l)
    if [ "$LOADED" -ge "$EXPECTED" ]; then
        echo ""
        echo -e "${GREEN}════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ✅ Все ${EXPECTED} моделей загружены!${NC}"
        echo -e "${GREEN}  🟢 Стек готов к работе${NC}"
        echo -e "${GREEN}════════════════════════════════════════${NC}"
        break
    else
        echo -e "  ${YELLOW}📊${NC} ${BOLD}${LOADED}/${EXPECTED}${NC} моделей"
        sleep 3
    fi
done
