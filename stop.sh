#!/bin/bash
# Скрипт для остановки всех сервисов AI-стека

cd "$(cd "$(dirname "$0")" && pwd)"

if [ -t 1 ]; then
    GREEN='\033[1;32m'; YELLOW='\033[1;33m'
    BLUE='\033[1;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; BLUE=''; BOLD=''; NC=''
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}  Остановка AI стека${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

docker compose -f "./docker-compose.yaml" down 2>&1 | sed 's/^/   /'

echo ""
echo -e "${GREEN}✅${NC} ${BOLD}Контейнеры остановлены${NC}"
echo ""
