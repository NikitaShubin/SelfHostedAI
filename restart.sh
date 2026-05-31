#!/bin/bash
# Скрипт для перезапуска AI-стека (остановка + запуск)

cd "$(cd "$(dirname "$0")" && pwd)"

if [ -t 1 ]; then
    GREEN='\033[1;32m'; RED='\033[1;31m'; YELLOW='\033[1;33m'
    BLUE='\033[1;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; BOLD=''; DIM=''; NC=''
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}  Перезапуск AI стека${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

# Предзагрузка образов для параллельной сборки:
echo -e "${BOLD}📥 Предзагрузка Docker образов...${NC}"
IMAGES=$(
    {
        grep "^FROM" */Dockerfile | awk '{print $2}';
        grep "image:" docker-compose.yaml | awk '{print $2}';
    } | sort -u
)

for img in $IMAGES; do
    docker pull "$img" &
done
wait

echo -e "  ${GREEN}✅${NC} Все образы загружены"
echo ""

# Останавливаем и запускаем:
echo -e "${YELLOW}⏹  Остановка сервисов...${NC}"
"./stop.sh"
echo ""

echo -e "${GREEN}▶️  Запуск сервисов...${NC}"
"./run.sh"
