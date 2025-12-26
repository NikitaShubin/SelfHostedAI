# voice_bridge/bridge.py - голосовой мост между пользователем и Ollama
# Записывает речь -> распознает -> отправляет в LLM -> озвучивает ответ

import whisper
import requests
import pyaudio
import wave
import tempfile
import os
import pyttsx3

# Инициализация синтезатора речи
tts_engine = pyttsx3.init()

# Загружаем модель Whisper для распознавания речи
model = whisper.load_model("base")
# Доступны варианты: 'tiny' (наименьшая), 'small', 'base', 'medium', 'large'

# Настройки аудиозаписи
CHUNK = 1024        # Размер блока аудиоданных
FORMAT = pyaudio.paInt16  # 16-битный аудиоформат
CHANNELS = 1        # Моно-звук
RATE = 16000        # Частота дискретизации (стандартная для распознавания речи)
RECORD_SECONDS = 5  # Длительность записи


def record_audio():
    """Записывает аудио с микрофона и сохраняет во временный файл."""
    p = pyaudio.PyAudio()
    # Открываем поток для записи
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    print("Записываю... Говорите сейчас.")
    for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)
    print("Запись окончена.")
    stream.stop_stream()
    stream.close()
    p.terminate()

    # Сохраняем во временный WAV-файл
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wf = wave.open(f.name, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        return f.name  # Возвращаем путь к файлу


def transcribe_with_whisper(audio_path):
    """Транскрибирует аудиофайл с помощью Whisper."""
    result = model.transcribe(
        audio_path,
        # language="ru",  # Можно указать язык для лучшего распознавания
    )
    return result["text"]


def ask_ollama(prompt):
    """Отправляет текстовый запрос в Ollama API."""
    # URL берётся из переменной окружения или используется значение по умолчанию
    url = f"{os.environ.get('OLLAMA_HOST', 'http://ollama:11434')}/api/generate"
    data = {
        # "model": "llama3.1:8b-instruct-q4_K_M",  # Можно указать конкретную модель
        "prompt": prompt,
        "stream": False  # Не использовать потоковый ответ
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        return response.json()["response"]
    else:
        return f"Ошибка: {response.status_code}"


if __name__ == "__main__":
    print("Голосовой мост запущен. Для выхода нажмите Ctrl+C.")
    try:
        while True:
            # Ждём нажатия Enter для начала записи
            input("Нажмите Enter, чтобы начать запись...")
            
            # 1. Запись речи
            audio_file = record_audio()
            
            # 2. Распознавание речи
            text = transcribe_with_whisper(audio_file)
            os.unlink(audio_file)  # Удаляем временный файл
            print(f"Вы сказали: {text}")
            
            # 3. Отправка в Ollama (если есть текст)
            if text.strip():
                answer = ask_ollama(text)
                print(f"Ollama отвечает: {answer}")
                
                # 4. Озвучивание ответа
                tts_engine.say(answer)
                tts_engine.runAndWait()
            print("-" * 40)
    except KeyboardInterrupt:
        print("\nЗавершение работы.")