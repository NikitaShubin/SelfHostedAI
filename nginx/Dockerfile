# Nginx с автоматической генерацией SSL сертификатов

# hadolint global ignore = DL3018  # Не фиксируем версии, т.к. в этом образе нужны свежие пакеты

FROM nginx:alpine

# Устанавливаем openssl для генерации сертификатов
RUN apk add --no-cache openssl

# Копируем конфигурацию nginx
COPY nginx.conf /etc/nginx/nginx.conf

# Копируем скрипт для генерации сертификатов
# Скрипт выполнится автоматически при запуске контейнера (директория docker-entrypoint.d)
COPY generate-ssl.sh /docker-entrypoint.d/40-generate-ssl.sh
RUN chmod +x /docker-entrypoint.d/40-generate-ssl.sh

# Открываем HTTP и HTTPS порты
EXPOSE 80 443

# Оставляем стандартный entrypoint nginx (он выполнит наши скрипты в /docker-entrypoint.d/)
CMD ["nginx", "-g", "daemon off;"]