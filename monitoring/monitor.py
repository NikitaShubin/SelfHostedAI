#!/usr/bin/env python3
# Скрипт мониторинга ресурсов системы и контейнера Ollama
# ВЕРСИЯ С ТОЧНЫМ GPU UTILIZATION (0% если есть другие процессы)

import os
import time
import threading
from collections import deque
from datetime import datetime
import logging
import json
import subprocess

import psutil
try:
    import pynvml
    NVIDIA_AVAILABLE = True
except ImportError:
    NVIDIA_AVAILABLE = False

from flask import Flask, render_template, jsonify

# Настройка логирования
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=getattr(logging, log_level), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '5'))
RETENTION_TIME = int(os.getenv('RETENTION_TIME', '3600'))
BUFFER_SIZE = RETENTION_TIME // UPDATE_INTERVAL

# Глобальные переменные
total_system_ram_gb = psutil.virtual_memory().total / (1024**3)
metrics = {
    'timestamps': deque(maxlen=BUFFER_SIZE),
    'system': {
        'cpu': deque(maxlen=BUFFER_SIZE),
        'ram_percent': deque(maxlen=BUFFER_SIZE),
        'ram_gb': deque(maxlen=BUFFER_SIZE),
        'gpu_util': deque(maxlen=BUFFER_SIZE),
        'gpu_mem': deque(maxlen=BUFFER_SIZE),
    },
    'ollama': {
        'cpu': deque(maxlen=BUFFER_SIZE),
        'ram_percent': deque(maxlen=BUFFER_SIZE),
        'ram_gb': deque(maxlen=BUFFER_SIZE),
        'gpu_util': deque(maxlen=BUFFER_SIZE),
        'gpu_mem': deque(maxlen=BUFFER_SIZE),
    }
}

gpu_handles = []
gpu_count = 0
last_cpu_stats = None

def init_gpu():
    """Инициализация доступа к GPU через NVML"""
    global gpu_handles, gpu_count, NVIDIA_AVAILABLE
    if not NVIDIA_AVAILABLE:
        logger.warning("⚠️ PyNVML не установлен, GPU метрики будут нулевыми")
        return False
    
    try:
        pynvml.nvmlInit()
        gpu_count = pynvml.nvmlDeviceGetCount()
        logger.info(f"✅ Найдено GPU: {gpu_count}")
        
        for i in range(gpu_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            gpu_handles.append(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            logger.info(f"  GPU {i}: {name}")
        
        return True
    except Exception as e:
        logger.error(f"❌ NVML ошибка: {e}")
        NVIDIA_AVAILABLE = False
        return False

def get_system_metrics():
    """Сбор метрик всей системы"""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        
        gpu_util = 0
        gpu_mem = 0
        
        if NVIDIA_AVAILABLE and gpu_handles:
            total_util = 0
            total_mem_used = 0
            total_mem_total = 0
            
            for handle in gpu_handles:
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    total_util += util.gpu
                    
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    total_mem_used += mem_info.used
                    total_mem_total += mem_info.total
                except Exception as e:
                    logger.debug(f"Ошибка получения GPU метрик: {e}")
                    pass
            
            gpu_util = total_util / gpu_count if gpu_count > 0 else 0
            gpu_mem = (total_mem_used / total_mem_total * 100) if total_mem_total > 0 else 0
        
        return {
            'cpu': cpu,
            'ram_percent': mem.percent,
            'ram_gb': mem.used / (1024**3),
            'gpu_util': gpu_util,
            'gpu_mem': gpu_mem
        }
    except Exception as e:
        logger.error(f"❌ Ошибка сбора системных метрик: {e}", exc_info=True)
        return {'cpu': 0, 'ram_percent': 0, 'ram_gb': 0, 'gpu_util': 0, 'gpu_mem': 0}

def get_processes_on_gpu(handle):
    """Получить все процессы на GPU с использованием памяти"""
    processes = {}
    try:
        # Compute процессы (CUDA)
        compute_procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        for proc in compute_procs:
            processes[proc.pid] = getattr(proc, 'usedGpuMemory', 0)
    except Exception as e:
        logger.debug(f"Ошибка получения compute процессов: {e}")
    
    try:
        # Graphics процессы
        graphics_procs = pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
        for proc in graphics_procs:
            prev_mem = processes.get(proc.pid, 0)
            processes[proc.pid] = prev_mem + getattr(proc, 'usedGpuMemory', 0)
    except Exception as e:
        logger.debug(f"Ошибка получения graphics процессов: {e}")
    
    return processes

def get_ollama_container_pids():
    """Получить хостовые PID всех процессов контейнера Ollama"""
    try:
        result = subprocess.run([
            'curl', '-s', '--unix-socket', '/var/run/docker.sock',
            'http://localhost/containers/ollama/top?ps_args=aux'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            logger.debug("Не удалось получить список процессов Ollama через Docker API")
            return set()
        
        data = json.loads(result.stdout)
        
        if 'Processes' not in data or 'Titles' not in data:
            logger.debug("Неправильный формат ответа Docker API")
            return set()
        
        # Находим индекс колонки PID
        titles = data['Titles']
        pid_index = None
        for idx, title in enumerate(titles):
            if title == 'PID':
                pid_index = idx
                break
        
        if pid_index is None:
            logger.warning("PID column not found in docker top output")
            return set()
        
        # Собираем все PID (это хостовые PID!)
        pids = set()
        for process in data['Processes']:
            if pid_index < len(process):
                try:
                    pid = int(process[pid_index])
                    pids.add(pid)
                except (ValueError, IndexError):
                    continue
        
        if pids:
            logger.debug(f"Найдено {len(pids)} процессов в контейнере Ollama: {sorted(pids)}")
        
        return pids
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения PID Ollama: {e}", exc_info=True)
        return set()

def get_ollama_metrics():
    """Сбор метрик контейнера Ollama"""
    global last_cpu_stats
    
    try:
        # Получаем основные stats через Docker API
        result = subprocess.run([
            'curl', '-s', '--unix-socket', '/var/run/docker.sock',
            'http://localhost/containers/ollama/stats?stream=false&one-shot=true'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            logger.debug("Не удалось получить stats контейнера Ollama")
            return {'cpu': 0, 'ram_percent': 0, 'ram_gb': 0, 'gpu_util': 0, 'gpu_mem': 0}
        
        stats = json.loads(result.stdout)
        
        # CPU расчет через delta
        cpu_percent = 0
        if last_cpu_stats is None:
            last_cpu_stats = stats
        else:
            try:
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           last_cpu_stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                              last_cpu_stats['precpu_stats']['system_cpu_usage']
                if system_delta > 0:
                    num_cpus = len(stats['cpu_stats']['cpu_usage']['percpu_usage'])
                    cpu_percent = (cpu_delta / system_delta) * num_cpus * 100
            except Exception as e:
                logger.debug(f"Ошибка расчета CPU: {e}")
                pass
            
            last_cpu_stats = stats
        
        # RAM - используем абсолютное значение и процент от общей RAM системы
        ram_gb = 0
        ram_percent = 0
        if 'memory_stats' in stats:
            memory_stats = stats['memory_stats']
            usage = memory_stats.get('usage', 0)
            ram_gb = usage / (1024**3)
            # Процент от общей RAM системы (не от лимита контейнера!)
            ram_percent = (ram_gb / total_system_ram_gb * 100) if total_system_ram_gb > 0 else 0
            # Ограничиваем до 100%
            ram_percent = min(ram_percent, 100.0)
        
        # GPU метрики - считаем ТОЛЬКО для процессов Ollama
        gpu_util = 0
        gpu_mem_percent = 0
        
        if NVIDIA_AVAILABLE and gpu_handles:
            ollama_pids = get_ollama_container_pids()
            
            if not ollama_pids:
                logger.debug("Нет процессов Ollama для мониторинга GPU")
                return {
                    'cpu': round(cpu_percent, 2),
                    'ram_percent': round(ram_percent, 2),
                    'ram_gb': round(ram_gb, 2),
                    'gpu_util': 0,
                    'gpu_mem': 0
                }
            
            # Общая память всех GPU для расчета процентов
            total_mem_total = 0
            for handle in gpu_handles:
                try:
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    total_mem_total += mem_info.total
                except:
                    pass
            
            # Собираем GPU метрики только для процессов Ollama
            total_ollama_gpu_mem_bytes = 0
            ollama_gpu_ids = set()
            
            for handle in gpu_handles:
                try:
                    # Получаем все процессы на этом GPU
                    gpu_processes = get_processes_on_gpu(handle)
                    
                    # Проверяем, есть ли процессы ollama на этом GPU
                    has_ollama_on_this_gpu = False
                    for pid in ollama_pids:
                        if pid in gpu_processes:
                            has_ollama_on_this_gpu = True
                            total_ollama_gpu_mem_bytes += gpu_processes[pid]
                    
                    # Если есть хотя бы один процесс ollama на этом GPU, запоминаем ID
                    if has_ollama_on_this_gpu:
                        gpu_id = gpu_handles.index(handle)
                        ollama_gpu_ids.add(gpu_id)
                    
                except Exception as e:
                    logger.debug(f"Ошибка получения GPU процессов: {e}")
                    pass
            
            # Рассчитываем процент использования памяти (от всех GPU)
            gpu_mem_percent = (total_ollama_gpu_mem_bytes / total_mem_total * 100) if total_mem_total > 0 else 0
            
            # === ВОТ ТУТ ГЛАВНАЯ ПРАВКА ===
            # GPU UTILIZATION: NVML НЕ ДАЕТ per-process utilization
            # РЕШЕНИЕ: Показываем 0%, если есть другие процессы на GPU, иначе показываем общую utilization
            
            if ollama_gpu_ids:
                # Проверяем, есть ли другие процессы на GPU, где есть Ollama
                other_processes_found = False
                for gpu_id in ollama_gpu_ids:
                    try:
                        handle = gpu_handles[gpu_id]
                        gpu_processes = get_processes_on_gpu(handle)
                        
                        for pid in gpu_processes:
                            if pid not in ollama_pids:
                                other_processes_found = True
                                logger.debug(f"Найден другой процесс {pid} на GPU {gpu_id}")
                                break
                        
                        if other_processes_found:
                            break
                    except:
                        pass
                
                if other_processes_found:
                    # Если есть другие процессы, ставим 0% чтобы не вводить в заблуждение
                    gpu_util = 0
                    logger.warning(f"⚠️ На GPU {ollama_gpu_ids} есть другие процессы, Ollama GPU utilization = 0%")
                else:
                    # ТОЛЬКО если на GPU есть только Ollama процессы, показываем реальную utilization
                    total_util = 0
                    for gpu_id in ollama_gpu_ids:
                        try:
                            handle = gpu_handles[gpu_id]
                            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                            total_util += util.gpu
                        except:
                            pass
                    
                    gpu_util = total_util / len(ollama_gpu_ids) if ollama_gpu_ids else 0
                    logger.debug(f"✅ На GPU {ollama_gpu_ids} только Ollama, utilization = {gpu_util:.1f}%")
            else:
                gpu_util = 0
        
        return {
            'cpu': round(cpu_percent, 2),
            'ram_percent': round(ram_percent, 2),
            'ram_gb': round(ram_gb, 2),
            'gpu_util': round(gpu_util, 2),
            'gpu_mem': round(gpu_mem_percent, 2)
        }
    except Exception as e:
        logger.error(f"❌ Ошибка метрик Ollama: {e}", exc_info=True)
        return {'cpu': 0, 'ram_percent': 0, 'ram_gb': 0, 'gpu_util': 0, 'gpu_mem': 0}

def collect_metrics():
    """Фоновый сбор метрик в бесконечном цикле"""
    logger.info("=== Запуск фонового сбора метрик ===")
    init_gpu()
    
    global last_cpu_stats
    last_cpu_stats = None
    
    iteration = 0
    while True:
        try:
            iteration += 1
            timestamp = datetime.now().isoformat()
            
            sys_metrics = get_system_metrics()
            ollama_metrics = get_ollama_metrics()
            
            metrics['timestamps'].append(timestamp)
            for key in metrics['system']:
                if key in sys_metrics:
                    metrics['system'][key].append(sys_metrics[key])
            for key in metrics['ollama']:
                if key in ollama_metrics:
                    metrics['ollama'][key].append(ollama_metrics[key])
            
            if iteration % 3 == 0:
                sys_str = f"CPU={sys_metrics['cpu']:.1f}% RAM={sys_metrics['ram_percent']:.1f}%({sys_metrics['ram_gb']:.1f}GB) GPU={sys_metrics['gpu_util']:.1f}%({sys_metrics['gpu_mem']:.1f}% mem)"
                ollama_str = f"CPU={ollama_metrics['cpu']:.1f}% RAM={ollama_metrics['ram_percent']:.1f}%({ollama_metrics['ram_gb']:.1f}GB) GPU={ollama_metrics['gpu_util']:.1f}%({ollama_metrics['gpu_mem']:.1f}% mem)"
                logger.info(f"✅ Система: {sys_str} | Ollama: {ollama_str}")
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле: {e}", exc_info=True)
        
        time.sleep(UPDATE_INTERVAL)

@app.route('/')
def index():
    return render_template('index.html',
                         update_interval=UPDATE_INTERVAL * 1000,
                         retention_minutes=RETENTION_TIME // 60)

@app.route('/api/metrics')
def get_metrics_api():
    return jsonify({
        'timestamps': list(metrics['timestamps']),
        'system': {k: list(v) for k, v in metrics['system'].items()},
        'ollama': {k: list(v) for k, v in metrics['ollama'].items()}
    })

@app.route('/api/system-info')
def get_system_info():
    """Возвращает информацию о системе"""
    global total_system_ram_gb, gpu_count, gpu_handles, NVIDIA_AVAILABLE
    
    # Получаем количество CPU ядер
    cpu_cores = psutil.cpu_count()
    
    # Получаем общий объем GPU памяти
    total_gpu_mem_gb = 0
    if NVIDIA_AVAILABLE and gpu_handles:
        for handle in gpu_handles:
            try:
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                total_gpu_mem_gb += mem_info.total / (1024**3)
            except Exception as e:
                logger.debug(f"Ошибка получения памяти GPU: {e}")
    
    return jsonify({
        'success': True,
        'cpu_cores': cpu_cores,
        'total_ram_gb': round(total_system_ram_gb, 2),
        'total_gpus': gpu_count,
        'total_gpu_mem_gb': round(total_gpu_mem_gb, 2)
    })

logger.info("=== ИНИЦИАЛИЗАЦИЯ МОНИТОРИНГА ===")
logger.info(f"Общая RAM системы: {total_system_ram_gb:.1f} GB")
collector_thread = threading.Thread(target=collect_metrics, daemon=True)
collector_thread.start()
logger.info(f"Фоновый поток запущен: {collector_thread.is_alive()}")

if __name__ == '__main__':
    logger.info("🚀 Flask сервер запускается на порту 5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)