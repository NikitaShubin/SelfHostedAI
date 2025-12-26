# Голосовой мост - преобразует речь в текст и обратно
# Использует Whisper для распознавания речи и pyttsx3 для синтеза

FROM python:3.11-slim-bookworm
# Устанавливаем зависимости для работы со звуком
RUN apt-get update && apt-get install -y --no-install-recommends alsa-utils portaudio19-dev python3-dev gcc
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bridge.py .
CMD ["python", "bridge.py"]  # Запуск основного скрипта