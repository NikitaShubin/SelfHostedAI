#!/bin/bash
# Основной скрипт запуска AI-стека

cd "$(cd "$(dirname "$0")" && pwd)" || exit

if [ -t 1 ]; then
    GREEN='\033[1;32m'; RED='\033[1;31m'; YELLOW='\033[1;33m'
    BLUE='\033[1;36m'; PURPLE='\033[1;35m'; CYAN='\033[1;34m'
    BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; PURPLE=''; CYAN=''; BOLD=''; DIM=''; NC=''
fi

source "./lib.sh"

OLLAMA_PORT=$(get_host_port ollama 11434)
DASHBOARD_PORT=$(get_host_port dashboard 5000)
WEBUI_PORT=$(get_host_port webui 8080)

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}  Запуск AI стека${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

echo -e "${BOLD}🔍 Проверка портов...${NC}"
if ! check_port_conflicts \
    "${OLLAMA_PORT}:Ollama" \
    "${DASHBOARD_PORT}:Dashboard" \
    "${WEBUI_PORT}:WebUI"; then
    echo ""
    echo -e "${YELLOW}💡 Измените порты в docker-compose.yaml и перезапустите${NC}"
    exit 1
fi
echo -e "  ${GREEN}✅ Все порты свободны${NC}"
echo ""

echo -e "${BOLD}🚀 Сборка и запуск контейнеров...${NC}"
docker compose build 2>&1 | sed 's/^/   /'
docker compose up -d 2>&1 | sed 's/^/   /'
echo ""

EXPECTED=$(grep -v '^#' "./models.txt" 2>/dev/null | grep -v '^$' | sed 's/#.*$//' | wc -l)
echo -e "${DIM}Ожидается моделей:${NC} ${BOLD}${EXPECTED}${NC}"

echo ""
echo -e "${DIM}⏳ Ожидание запуска сервисов...${NC}"

WAIT_START=$(date +%s)
TIMEOUT=120

wait_service() {
    local name=$1 url=$2 color=$3
    echo -ne "  ${DIM}${name}...${NC}"
    while true; do
        if timeout 3 curl -s "$url" > /dev/null 2>&1; then
            echo -e "\r  ${color}✅ ${name}${NC}"
            return 0
        fi
        elapsed=$(( $(date +%s) - WAIT_START ))
        if [ "$elapsed" -ge "$TIMEOUT" ]; then
            echo -e "\r  ${RED}❌ ${name} (таймаут ${TIMEOUT}с)${NC}"
            echo "   Проверьте: docker compose logs ${name,,}"
            return 1
        fi
        echo -n "."
        sleep 2
    done
}

wait_service "Ollama"    "http://localhost:${OLLAMA_PORT}/api/tags"       "$GREEN"
wait_service "Dashboard" "http://localhost:${DASHBOARD_PORT}/api/system-info" "$PURPLE"
wait_service "WebUI"     "http://localhost:${WEBUI_PORT}"                  "$CYAN"

echo ""
echo -e "${GREEN}✅ Все сервисы запущены${NC}"
echo ""

wait_start=$(date +%s)
LOAD_TIMEOUT=600

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

    if [ "$elapsed" -ge "$LOAD_TIMEOUT" ]; then
        echo -e "${RED}════════════════════════════════════════${NC}"
        echo -e "${RED}  ❌ Таймаут загрузки (${LOAD_TIMEOUT}с)${NC}"
        echo -e "${RED}  Не все модели загрузились${NC}"
        echo -e "${RED}  Проверьте: docker compose logs ollama${NC}"
        echo -e "${RED}════════════════════════════════════════${NC}"
        break
    fi

    LOADED=$(curl -s "http://localhost:${OLLAMA_PORT}/api/tags" | grep -o '"name"' | wc -l)
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
