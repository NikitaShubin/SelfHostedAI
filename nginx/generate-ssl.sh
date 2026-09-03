#!/bin/sh
# Автогенерация локального CA и серверного сертификата, покрывающего все
# внешние IP хоста (передаются через env SSL_SAN_IPS, собранные на хосте).
# Выполняется при запуске контейнера nginx.
#
# Принцип стабильности:
#  - Корневой CA создаётся ОДИН раз (только если файлов нет). Его ключ не
#    меняется, поэтому клиенты импортируют ca.crt один раз и доверяют всем
#    последующим серверным сертификатам — при ./restart.sh обновлять
#    доверие на клиентах не нужно.
#  - Серверный сертификат перевыпускается ТОЛЬКО когда меняется набор IP в
#    SAN (сравнение хеша). Если IP не изменились — файлы не трогаем.

SSL_DIR="/etc/nginx/ssl"
CA_CRT="$SSL_DIR/ca.crt"
CA_KEY="$SSL_DIR/ca.key"
CERT_CRT="$SSL_DIR/localhost.crt"
CERT_KEY="$SSL_DIR/localhost.key"
CSR="$SSL_DIR/localhost.csr"
HASH_FILE="$SSL_DIR/san_hash"

# Сроки действия
CA_DAYS=3650        # ~10 лет, чтобы максимально отложить переустановку CA
CERT_DAYS=825

mkdir -p "$SSL_DIR"

# --- 1. Корневой CA (однократно) ---
if [ ! -f "$CA_CRT" ] || [ ! -f "$CA_KEY" ]; then
    echo "🔐 Создание корневого CA (один раз)..."
    openssl req -x509 -nodes -days "$CA_DAYS" -newkey rsa:4096 \
        -keyout "$CA_KEY" -out "$CA_CRT" \
        -subj "/C=US/ST=State/L=City/O=SelfHosted AI/CN=SelfHosted AI Local CA" 2>/dev/null
    if [ -f "$CA_CRT" ] && [ -f "$CA_KEY" ]; then
        echo "   ✅ CA создан: $CA_CRT"
        echo "   ⚠️  Импортируйте ca.crt в доверенные на клиентах один раз."
    else
        echo "   ❌ Не удалось создать CA"
    fi
else
    echo "✅ CA уже существует (ключ стабилен — доверие клиентов сохраняется)"
fi

# --- 2. Формируем SAN из внешних IP хоста ---
SAN="DNS:localhost,IP:127.0.0.1"
if [ -n "$SSL_SAN_IPS" ]; then
    SAN="$SAN,$SSL_SAN_IPS"
fi

# --- 3. Перевыпускаем серверный сертификат только при изменении SAN ---
OLD_HASH=""
[ -f "$HASH_FILE" ] && OLD_HASH=$(cat "$HASH_FILE" 2>/dev/null)
NEW_HASH=$(printf '%s' "$SAN" | md5sum | awk '{print $1}')

if [ ! -f "$CERT_CRT" ] || [ ! -f "$CERT_KEY" ] || [ "$OLD_HASH" != "$NEW_HASH" ]; then
    echo "🔐 (Пере)генерация серверного сертификата..."
    echo "   SAN: $SAN"

    if openssl req -new -newkey rsa:2048 -nodes \
        -keyout "$CERT_KEY" -out "$CSR" \
        -subj "/C=US/ST=State/L=City/O=Localhost/CN=localhost" 2>/dev/null \
        && printf "subjectAltName = %s\n" "$SAN" > "$SSL_DIR/san.cnf" \
        && openssl x509 -req -days "$CERT_DAYS" \
            -in "$CSR" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
            -out "$CERT_CRT" \
            -extfile "$SSL_DIR/san.cnf" 2>/dev/null; then
        printf '%s' "$NEW_HASH" > "$HASH_FILE"
        rm -f "$CSR" "$SSL_DIR/san.cnf"
        echo "   ✅ Серверный сертификат создан и подписан CA"
        echo "   Адреса: $SAN"
    else
        echo "   ❌ Ошибка при создании серверного сертификата"
        echo "   Nginx будет работать только по HTTP"
    fi
else
    echo "✅ Серверный сертификат актуален (набор IP не изменился)"
fi

# --- 4. Проверяем конфигурацию nginx ---
echo ""
echo "🔧 Проверка конфигурации nginx..."
nginx -t
