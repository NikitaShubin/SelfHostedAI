# Nginx с автоматической генерацией SSL сертификатов

FROM nginx:alpine

# Устанавливаем openssl для генерации сертификатов
RUN apk add --no-cache openssl

# Копируем конфигурацию nginx
COPY nginx.conf /etc/nginx/nginx.conf

# Копируем скрипт для генерации сертификатов
# Скрипт выполнится автоматически при запуске контейнера (директория docker-entrypoint.d)
COPY generate-ssl.sh /docker-entrypoint.d/40-generate-ssl.sh
RUN chmod +x /docker-entrypoint.d/40-generate-ssl.sh

EXPOSE 80 443  # Открываем HTTP и HTTPS порты

# Оставляем стандартный entrypoint nginx (он выполнит наши скрипты в /docker-entrypoint.d/)
CMD ["nginx", "-g", "daemon off;"]