#!/bin/bash
# Общие функции для AI-стека

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yaml"

# Извлекает хостовый порт из docker-compose.yaml
# Аргументы: service_name container_port
# Пример: get_host_port webui 8080 → 8081
get_host_port() {
    local service=$1 container_port=$2
    grep -A 30 "^  ${service}:" "$COMPOSE_FILE" | \
        awk -v cport="$container_port" '
            /ports:/ { found=1; next }
            found && /^[[:space:]]+-/ {
                line = $0
                gsub(/^[[:space:]]+-[[:space:]]*["'"'"']?/, "", line)
                gsub(/["'"'"'].*$/, "", line)
                gsub(/#.*/, "", line)
                n = split(line, parts, ":")
                # Format: host:hostport:containerport (3 parts) или hostport:containerport (2 parts)
                if (n == 3 && parts[3] == cport) { print parts[2]; exit }
                if (n == 2 && parts[2] == cport) { print parts[1]; exit }
            }
            found && /^[^ ]/ { exit }
        '
}

# Проверяет, не заняты ли порты
# Аргументы: "port:service_name" "port:service_name" ...
# Возвращает 0 если всё свободно, 1 если есть конфликт
check_port_conflicts() {
    local conflicts=0
    for port_info in "$@"; do
        local port=${port_info%%:*}
        local service=${port_info#*:}
        if ss -tlnp "sport = :${port}" 2>/dev/null | grep -q ":${port}"; then
            local proc
            proc=$(ss -tlnp "sport = :${port}" 2>/dev/null | \
                awk '/LISTEN/{for(i=1;i<=NF;i++) if($i~"users:") print $i}' | \
                sed 's/users:(("//;s/".*//')
            echo -e "  ${RED:-}⚠  Порт ${port} (${service}) занят${NC:-} — ${proc:-?}"
            conflicts=1
        fi
    done
    return $conflicts
}
