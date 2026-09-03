#!/bin/bash
# Общие функции для AI-стека

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yaml"

# Извлекает дефолтный (из ${VAR:-default}) хостовый порт сервиса из docker-compose.yaml
# Аргументы: service_name container_port
# Пример: get_default_host_port webui 8080 → 8080
get_default_host_port() {
    local service=$1 container_port=$2
    python3 - "$COMPOSE_FILE" "$service" "$container_port" <<'PYEOF'
import sys, re
compose_file, service, cport = sys.argv[1], sys.argv[2], sys.argv[3]
compose = open(compose_file).read()
in_svc = False
in_ports = False
for raw in compose.splitlines():
    line = raw.rstrip()
    indent = len(line) - len(line.lstrip())
    if re.match(r'^  ' + service + r':', line):
        in_svc = True
        continue
    if not in_svc:
        continue
    if re.match(r'^[^ ]', line):
        break
    if indent <= 2:
        break
    stripped = line.strip()
    if stripped.startswith('ports:'):
        in_ports = True
        continue
    if in_ports and stripped.startswith('-'):
        body = stripped[1:].strip()
        body = body.split('#')[0].strip().strip('"\'')
        parts = body.rsplit(':', 1)
        if len(parts) == 2 and parts[1] == cport:
            m = re.search(r'\$\{([A-Z_]+):-([0-9]+)\}', parts[0])
            if m:
                print(m.group(2))
            elif parts[0].isdigit():
                print(parts[0])
            break
    elif in_ports and indent < 6:
        in_ports = False
PYEOF
}

# Проверяет, свободен ли TCP-порт
port_is_free() {
    local port=$1
    ! ss -tln "sport = :${port}" 2>/dev/null | grep -q ":${port}"
}

# Подбирает первый свободный порт, начиная с заданного (инкремент +1)
find_free_port() {
    local port=$1
    while ! port_is_free "$port"; do
        port=$((port + 1))
    done
    echo "$port"
}

# Гарантирует свободные хост-порты и экспортирует их как переменные окружения.
# Аргументы: "VAR:SERVICE:CONTPORT" "VAR:SERVICE:CONTPORT" ...
# Экспортирует VAR=выбранный_порт. Использует дефолт из YAML, если он свободен,
# иначе — первый свободный.
# Принцип: переменная изначально не установлена → берём дефолт, подстраховываемся занятостью
ensure_free_ports() {
    local chosen=""   # соберём список для вывода
    for port_info in "$@"; do
        local var service contport
        var=${port_info%%:*}
        local rest=${port_info#*:}
        service=${rest%%:*}
        contport=${rest#*:}

        # Уважаем уже установленную извне переменную (explicit override)
        local existing
        existing=$(eval "printf '%s' \"\${$var}\"")
        if [ -n "$existing" ]; then
            chosen="$chosen ${var}=${existing}"
            continue
        fi

        local default
        default=$(get_default_host_port "$service" "$contport")
        if [ -z "$default" ]; then
            continue
        fi

        local effective
        if port_is_free "$default"; then
            effective=$default
        else
            effective=$(find_free_port "$((default + 1))")
            echo -e "  ${YELLOW:-}⚠  Порт ${default} (${service}) занят → использую ${effective}${NC:-}"
        fi

        export "$var=$effective"
        chosen="$chosen ${var}=${effective}"
    done
    if [ -n "$chosen" ]; then
        echo -e "  ${DIM:-}Порты:${NC:-}$chosen"
    fi
}

# Жёсткая проверка конфликтов портов (для флага --strict / STRICT_PORTS=1).
# Аргументы: "port:service_name" ...
# Возвращает 0 если всё свободно, 1 если есть конфликт.
check_port_conflicts() {
    local conflicts=0
    for port_info in "$@"; do
        local port=${port_info%%:*}
        local service=${port_info#*:}
        if ! port_is_free "$port"; then
            echo -e "  ${RED:-}⚠  Порт ${port} (${service}) занят${NC:-}"
            conflicts=1
        fi
    done
    return $conflicts
}

# Возвращает все внешние IPv4-адреса хоста (кроме loopback и интерфейсов
# Docker-мостов) в виде строки, готовой для SAN:
#   "IP:a.b.c.d,IP:e.f.g.h"
# Используется, чтобы сертификат автоматически покрывал ВСЕ сетевые карты.
get_external_host_ips() {
    ip -o addr show 2>/dev/null | awk '
        /inet / {
            iface=$2
            addr=$4
            sub(/\/.*/, "", addr)
            # исключаем loopback
            if (addr ~ /^127\./) next
            # исключаем интерфейсы Docker-мостов
            if (iface ~ /^(docker|veth|br-)/) next
            # исключаем docker bridge подсети (172.16.0.0/12)
            if (addr ~ /^172\.(1[6-9]|2[0-9]|3[01])\./) next
            all = all (all ? "," : "") "IP:" addr
        }
        END { print all }
    '
}

# Возвращает фактический хостовый порт контейнера (из docker inspect).
# Аргументы: container_name container_port
# Пример: get_running_host_port open-webui 8080 → 8081
# Возвращает пусто, если контейнер не запущен или порт не замаплен.
get_running_host_port() {
    local container=$1 container_port=$2
    docker inspect "$container" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null | \
        python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
key = '${container_port}/tcp'
m = (data or {}).get(key)
if m:
    print(m[0].get('HostPort', ''))
" 2>/dev/null
}
