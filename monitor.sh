#!/bin/bash
# Скрипт для мониторинга состояния сервисов AI-стека

cd "$(cd "$(dirname "$0")" && pwd)" || exit

if [ -t 1 ]; then
    GREEN='\033[1;32m'; RED='\033[1;31m'; YELLOW='\033[1;33m'
    BLUE='\033[1;36m'; PURPLE='\033[1;35m'; CYAN='\033[1;34m'
    BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; PURPLE=''; CYAN=''; BOLD=''; DIM=''; NC=''
fi

source "./lib.sh"

# Читаем фактические хостовые порты из запущенных контейнеров
# (те, что реально назначил docker; если контейнер не запущен — fallback на дефолт из YAML)
OLLAMA_PORT=$(get_running_host_port ollama 11434)
[ -z "$OLLAMA_PORT" ] && OLLAMA_PORT=$(get_default_host_port ollama 11434)
DASHBOARD_PORT=$(get_running_host_port ai-dashboard 5000)
[ -z "$DASHBOARD_PORT" ] && DASHBOARD_PORT=$(get_default_host_port dashboard 5000)
WEBUI_PORT=$(get_running_host_port open-webui 8080)
[ -z "$WEBUI_PORT" ] && WEBUI_PORT=$(get_default_host_port webui 8080)
NGINX_HTTP_PORT=$(get_running_host_port nginx-proxy 80)
[ -z "$NGINX_HTTP_PORT" ] && NGINX_HTTP_PORT=$(get_default_host_port nginx 80)
NGINX_HTTPS_PORT=$(get_running_host_port nginx-proxy 443)
[ -z "$NGINX_HTTPS_PORT" ] && NGINX_HTTPS_PORT=$(get_default_host_port nginx 443)

echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}  Состояние AI стека${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

echo -e "${BOLD}📦 Контейнеры:${NC}"
docker compose ps 2>&1
echo ""

echo -e "${BOLD}🌐 Сервисы:${NC}"

if timeout 5 curl -s "http://localhost:${DASHBOARD_PORT}/api/system-info" > /dev/null 2>&1; then
    echo -e "  ${PURPLE}✅${NC} Панель управления  ${BOLD}http://localhost:${DASHBOARD_PORT}${NC}"
else
    echo -e "  ${RED}❌${NC} Панель управления  ${DIM}недоступна${NC}"
fi

# WebUI: доступ через nginx (HTTPS/HTTP) и прямой порт (если замаплен)
WEBUI_OK=0
HTTPS_BASE="https://localhost"
[ "$NGINX_HTTPS_PORT" != "443" ] && HTTPS_BASE="https://localhost:${NGINX_HTTPS_PORT}"
if timeout 5 curl -sk -o /dev/null -w "%{http_code}" "$HTTPS_BASE/" | grep -qE "200|30[0-9]"; then
    echo -e "  ${CYAN}✅${NC} WebUI (HTTPS)      ${BOLD}${HTTPS_BASE}${NC}"
    WEBUI_OK=1
elif timeout 5 curl -s -o /dev/null "http://localhost:${NGINX_HTTP_PORT}/" 2>/dev/null; then
    echo -e "  ${CYAN}✅${NC} WebUI (HTTP)       ${BOLD}http://localhost:${NGINX_HTTP_PORT}${NC}"
    WEBUI_OK=1
fi

if [ -n "$WEBUI_PORT" ] && timeout 5 curl -s "http://localhost:${WEBUI_PORT}" > /dev/null 2>&1; then
    echo -e "  ${CYAN}✅${NC} WebUI (прямой)     ${BOLD}http://localhost:${WEBUI_PORT}${NC}"
    WEBUI_OK=1
fi

if [ "$WEBUI_OK" = "0" ]; then
    echo -e "  ${RED}❌${NC} WebUI              ${DIM}недоступен${NC}"
fi

if timeout 5 curl -s "http://localhost:${OLLAMA_PORT}/api/tags" > /dev/null 2>&1; then
    echo -e "  ${GREEN}✅${NC} Ollama API         ${BOLD}http://localhost:${OLLAMA_PORT}${NC}"
    MODELS=$(curl -s "http://localhost:${OLLAMA_PORT}/api/tags" | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//g')
    MODEL_COUNT=$(echo "$MODELS" | grep -c . 2>/dev/null)
    if [ "$MODEL_COUNT" -gt 0 ]; then
        echo -e "     ${DIM}Модели (${MODEL_COUNT}):${NC}"
        while IFS= read -r line; do echo "       • $line"; done <<< "$MODELS"
    fi
else
    echo -e "  ${RED}❌${NC} Ollama API         ${DIM}недоступен${NC}"
fi

# Активная загрузка: ищем реальные ollama pull процессы в контейнере
PULL_PROC=$(docker exec ollama ps aux 2>/dev/null | grep -E "[o]llama pull" | head -3)
if [ -n "$PULL_PROC" ]; then
    # Извлекаем имя модели из команды: ollama pull <model>
    MODEL=$(echo "$PULL_PROC" | grep -oP 'ollama pull \K\S+' | head -1)
    echo ""
    echo -e "     ${YELLOW}🔄${NC} Загружается: ${BOLD}${MODEL:-модель}${NC}"
fi

# Ошибки загрузки (только свежие, из последнего запуска инициализации)
LOGS=$(docker logs ollama --since=1m 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g')
ERROR=$(echo "$LOGS" | grep -iE "error.*(pull|manifest|not found|requires)" | grep -v "context canceled" | tail -3)
if [ -n "$ERROR" ]; then
    echo ""
    echo -e "     ${RED}❌${NC} Ошибка загрузки:"
    while IFS= read -r line; do echo "       $line"; done <<< "$ERROR"
fi
