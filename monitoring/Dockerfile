# Образ Python для сервиса мониторинга ресурсов
# Версия python:3.11-slim выбрана для баланса между размером и функциональностью

FROM python:3.11-slim

WORKDIR /app

# Установка необходимых пакетов
RUN apt-get update && apt-get install -y \
    gcc curl ca-certificates gnupg lsb-release procps \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    flask==3.0.0 \
    psutil==5.9.8 \
    nvidia-ml-py==12.535.133 \
    requests-unixsocket==0.3.0

COPY monitor.py .
COPY templates ./templates

EXPOSE 5000

CMD ["python", "monitor.py"]