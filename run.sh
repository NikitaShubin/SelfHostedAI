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

# Подсчитываем ожидаемые модели (незакомментированные строки в models.txt)
EXPECTED=$(grep -v '^#' "./models.txt" 2>/dev/null | grep -v '^$' | sed 's/#.*$//' | wc -l)
echo -e "${DIM}Ожидается моделей:${NC} ${BOLD}${EXPECTED}${NC}"
echo ""

wait_start=$(date +%s)
while true; do
    clear

    elapsed=$(( $(date +%s) - wait_start ))
    mins=$(( elapsed / 60 ))
    secs=$(( elapsed % 60 ))
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Запуск AI стека — прошло ${mins}м ${secs}с${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo ""

    "./monitor.sh"
    echo ""

    if timeout 5 curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        LOADED=$(curl -s http://localhost:11434/api/tags | grep -o '"name"' | wc -l)
        if [ "$LOADED" -ge "$EXPECTED" ]; then
            echo ""
            echo -e "${GREEN}════════════════════════════════════════${NC}"
            echo -e "${GREEN}  ✅ Все ${EXPECTED} моделей загружены!${NC}"
            echo -e "${GREEN}  🟢 Стек готов к работе${NC}"
            echo -e "${GREEN}════════════════════════════════════════${NC}"
            break
        else
            echo -e "  ${YELLOW}📊${NC} ${BOLD}${LOADED}/${EXPECTED}${NC} моделей загружено"
            echo -e "  ${DIM}⏳ Ожидание завершения загрузки...${NC}"
            sleep 3
        fi
    else
        echo -e "  ${DIM}⏳ Ожидание запуска Ollama...${NC}"
        sleep 2
    fi
done
