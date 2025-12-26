#!/usr/bin/env python3
"""Голосовой мост между пользователем и Ollama.

Модуль записывает речь, распознаёт её с помощью Whisper,
отправляет текст в LLM через Ollama API и озвучивает ответ.
"""

import os
import tempfile
import wave
from pathlib import Path

import pyaudio
import pyttsx3
import requests
import whisper

# Инициализация синтезатора речи
tts_engine = pyttsx3.init()

# Загружаем модель Whisper для распознавания речи
model = whisper.load_model('base')
# Доступны варианты: 'tiny' (наименьшая), 'small', 'base', 'medium', 'large'

# Настройки аудиозаписи
CHUNK = 1024  # Размер блока аудиоданных
FORMAT = pyaudio.paInt16  # 16-битный аудиоформат
CHANNELS = 1  # Моно-звук
RATE = 16000  # Частота дискретизации (стандартная для распознавания речи)
RECORD_SECONDS = 5  # Длительность записи

# Константы для HTTP
HTTP_OK = 200
REQUEST_TIMEOUT = 30.0


def record_audio() -> str:
    """Записывает аудио с микрофона и сохраняет во временный файл."""
    p = pyaudio.PyAudio()
    # Открываем поток для записи
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )
    frames = []
    for _ in range(int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()

    # Сохраняем во временный WAV-файл
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        with wave.open(f.name, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
        return f.name  # Возвращаем путь к файлу


def transcribe_with_whisper(audio_path: str) -> str:
    """Транскрибирует аудиофайл с помощью Whisper."""
    result = model.transcribe(audio_path)
    return result['text']


def ask_ollama(prompt: str) -> str:
    """Отправляет текстовый запрос в Ollama API."""
    # URL берётся из переменной окружения или используется значение по умолчанию
    url = f'{os.environ.get("OLLAMA_HOST", "http://ollama:11434")}/api/generate'
    data = {
        'prompt': prompt,
        'stream': False,  # Не использовать потоковый ответ
    }
    response = requests.post(url, json=data, timeout=REQUEST_TIMEOUT)
    if response.status_code == HTTP_OK:
        return response.json()['response']
    return f'Ошибка: {response.status_code}'


if __name__ == '__main__':
    try:
        while True:
            # Ждём нажатия Enter для начала записи
            input('Нажмите Enter, чтобы начать запись...')

            # 1. Запись речи
            audio_file = record_audio()

            # 2. Распознавание речи
            text = transcribe_with_whisper(audio_file)
            Path(audio_file).unlink()  # Удаляем временный файл

            # 3. Отправка в Ollama (если есть текст)
            if text.strip():
                answer = ask_ollama(text)

                # 4. Озвучивание ответа
                tts_engine.say(answer)
                tts_engine.runAndWait()
    except KeyboardInterrupt:
        pass
