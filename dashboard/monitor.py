#!/usr/bin/env python3
# Скрипт мониторинга ресурсов системы и контейнера Ollama
# ВЕРСИЯ С ИСПРАВЛЕННЫМИ RAM/CPU/GPU МЕТРИКАМИ

import os
import re
import time
import threading
import urllib.request
from collections import deque
from datetime import datetime
import logging
import json
import subprocess

import psutil

try:
    import pynvml  # type: ignore[import-untyped]

    NVIDIA_AVAILABLE = True
except ImportError:
    NVIDIA_AVAILABLE = False

from flask import Flask, render_template, jsonify

# Настройка логирования
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "5"))
RETENTION_TIME = int(os.getenv("RETENTION_TIME", "3600"))
BUFFER_SIZE = RETENTION_TIME // UPDATE_INTERVAL

# Глобальные переменные
total_system_ram_gb = psutil.virtual_memory().total / (1024**3)
metrics = {
    "timestamps": deque(maxlen=BUFFER_SIZE),
    "system": {
        "cpu": deque(maxlen=BUFFER_SIZE),
        "ram_percent": deque(maxlen=BUFFER_SIZE),
        "ram_gb": deque(maxlen=BUFFER_SIZE),
        "gpu_util": deque(maxlen=BUFFER_SIZE),
        "gpu_mem": deque(maxlen=BUFFER_SIZE),
    },
    "ollama": {
        "cpu": deque(maxlen=BUFFER_SIZE),
        "ram_percent": deque(maxlen=BUFFER_SIZE),
        "ram_gb": deque(maxlen=BUFFER_SIZE),
        "gpu_util": deque(maxlen=BUFFER_SIZE),
        "gpu_mem": deque(maxlen=BUFFER_SIZE),
    },
}

gpu_handles: list = []
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
            gpu_mem = (
                (total_mem_used / total_mem_total * 100) if total_mem_total > 0 else 0
            )

        return {
            "cpu": cpu,
            "ram_percent": mem.percent,
            "ram_gb": mem.used / (1024**3),
            "gpu_util": gpu_util,
            "gpu_mem": gpu_mem,
        }
    except Exception as e:
        logger.error(f"❌ Ошибка сбора системных метрик: {e}", exc_info=True)
        return {"cpu": 0, "ram_percent": 0, "ram_gb": 0, "gpu_util": 0, "gpu_mem": 0}


def get_compute_processes_on_gpu(handle):
    """Получить только CUDA/compute процессы на GPU с использованием памяти"""
    processes = {}
    try:
        compute_procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        for proc in compute_procs:
            processes[proc.pid] = getattr(proc, "usedGpuMemory", 0)
    except Exception as e:
        logger.debug(f"Ошибка получения compute процессов: {e}")
    return processes


def get_graphics_processes_on_gpu(handle):
    """Получить только graphics процессы на GPU с использованием памяти"""
    processes = {}
    try:
        graphics_procs = pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
        for proc in graphics_procs:
            processes[proc.pid] = getattr(proc, "usedGpuMemory", 0)
    except Exception as e:
        logger.debug(f"Ошибка получения graphics процессов: {e}")
    return processes


def get_per_process_gpu_utilization():
    """Получить per-process SM utilization для всех GPU.
    
    Возвращает {pid: {gpu_id: sm_util_percent}}
    Всегда получает последние доступные семплы (lastTimeStamp=0).
    """
    proc_util: dict[int, dict[int, int]] = {}
    for gpu_id, handle in enumerate(gpu_handles):
        try:
            samples = pynvml.nvmlDeviceGetProcessUtilization(handle, 0)
            for sample in samples:
                pid = sample.pid
                if pid not in proc_util:
                    proc_util[pid] = {}
                proc_util[pid][gpu_id] = sample.smUtil
        except Exception as e:
            logger.debug(f"Ошибка per-process utilization на GPU {gpu_id}: {e}")
    return proc_util


def compute_ollama_gpu_from_per_process(per_process_util, ollama_pids):
    """Вычислить Ollama GPU utilization из per-process данных NVML.
    
    Использует те же самые данные, что и system — гарантирует ollama <= system.
    """
    if gpu_count == 0 or not ollama_pids:
        return 0
    total_ollama_sm = 0
    for gpu_id in range(gpu_count):
        ollama_sm_sum = 0
        for pid in ollama_pids:
            proc = per_process_util.get(pid, {})
            if gpu_id in proc:
                ollama_sm_sum += proc[gpu_id]
        total_ollama_sm += min(ollama_sm_sum, 100)
    return total_ollama_sm / gpu_count


def get_ollama_container_pids():
    """Получить хостовые PID всех процессов контейнера Ollama"""
    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "--unix-socket",
                "/var/run/docker.sock",
                "http://localhost/containers/ollama/top?ps_args=aux",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.debug("Не удалось получить список процессов Ollama через Docker API")
            return set()

        data = json.loads(result.stdout)

        if "Processes" not in data or "Titles" not in data:
            logger.debug("Неправильный формат ответа Docker API")
            return set()

        titles = data["Titles"]
        pid_index = None
        for idx, title in enumerate(titles):
            if title == "PID":
                pid_index = idx
                break

        if pid_index is None:
            logger.warning("PID column not found in docker top output")
            return set()

        pids = set()
        for process in data["Processes"]:
            if pid_index < len(process):
                try:
                    pid = int(process[pid_index])
                    pids.add(pid)
                except (ValueError, IndexError):
                    continue

        if pids:
            logger.debug(
                f"Найдено {len(pids)} процессов в контейнере Ollama: {sorted(pids)}"
            )

        return pids

    except Exception as e:
        logger.error(f"❌ Ошибка получения PID Ollama: {e}", exc_info=True)
        return set()


def get_ollama_metrics():
    """Сбор метрик контейнера Ollama"""
    global last_cpu_stats

    try:
        # GPU метрики — замеряем ПЕРВЫМИ, до любых блокирующих вызовов
        gpu_util = 0
        gpu_mem_percent = 0

        if NVIDIA_AVAILABLE and gpu_handles:
            ollama_pids = get_ollama_container_pids()

            if ollama_pids:
                total_mem_total = 0
                for handle in gpu_handles:
                    try:
                        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        total_mem_total += mem_info.total
                    except Exception:
                        pass

                total_ollama_gpu_mem_bytes = 0
                for handle in gpu_handles:
                    try:
                        gpu_processes = get_compute_processes_on_gpu(handle)
                        for pid in ollama_pids:
                            if pid in gpu_processes:
                                total_ollama_gpu_mem_bytes += gpu_processes[pid]
                    except Exception as e:
                        logger.debug(f"Ошибка получения GPU процессов: {e}")
                        pass

                gpu_mem_percent = (
                    (total_ollama_gpu_mem_bytes / total_mem_total * 100)
                    if total_mem_total > 0
                    else 0
                )

                if gpu_count > 0:
                    per_process_util = get_per_process_gpu_utilization()
                    total_ollama_sm = 0
                    for gpu_id in range(gpu_count):
                        ollama_sm_sum = 0
                        for pid in ollama_pids:
                            proc = per_process_util.get(pid, {})
                            if gpu_id in proc:
                                ollama_sm_sum += proc[gpu_id]
                        total_ollama_sm += min(ollama_sm_sum, 100)
                    gpu_util = total_ollama_sm / gpu_count
                    if gpu_util > 0:
                        logger.debug(
                            f"✅ Ollama GPU util: {gpu_util:.1f}% "
                            f"(SM capped avg across {gpu_count} GPUs)"
                        )
                else:
                    gpu_util = 0

        # Получаем основные stats через Docker API
        result = subprocess.run(
            [
                "curl",
                "-s",
                "--unix-socket",
                "/var/run/docker.sock",
                "http://localhost/containers/ollama/stats?stream=false&one-shot=true",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.debug("Не удалось получить stats контейнера Ollama")
            return {
                "cpu": 0,
                "ram_percent": 0,
                "ram_gb": 0,
                "gpu_util": round(gpu_util, 2),
                "gpu_mem": round(gpu_mem_percent, 2),
            }

        stats = json.loads(result.stdout)

        # CPU расчет через delta (0-100%, где 100% = все ядра)
        cpu_percent = 0
        if last_cpu_stats is None:
            last_cpu_stats = stats
        else:
            try:
                cpu_delta = (
                    stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - last_cpu_stats["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                system_delta = (
                    stats["cpu_stats"]["system_cpu_usage"]
                    - last_cpu_stats["precpu_stats"]["system_cpu_usage"]
                )
                if system_delta > 0:
                    cpu_percent = (cpu_delta / system_delta) * 100
            except Exception as e:
                logger.debug(f"Ошибка расчета CPU: {e}")
                pass

            last_cpu_stats = stats

        # RAM — вычитаем page cache (Docker usage включает кеш ядра)
        ram_gb = 0
        ram_percent = 0
        if "memory_stats" in stats:
            memory_stats = stats["memory_stats"]
            usage_raw = memory_stats.get("usage", 0)
            cache = memory_stats.get("stats", {}).get("cache", 0)
            usage = max(0, usage_raw - cache)
            ram_gb = usage / (1024**3)
            ram_percent = (
                (ram_gb / total_system_ram_gb * 100) if total_system_ram_gb > 0 else 0
            )
            ram_percent = min(ram_percent, 100.0)

        return {
            "cpu": round(cpu_percent, 2),
            "ram_percent": round(ram_percent, 2),
            "ram_gb": round(ram_gb, 2),
            "gpu_util": round(gpu_util, 2),
            "gpu_mem": round(gpu_mem_percent, 2),
        }
    except Exception as e:
        logger.error(f"❌ Ошибка метрик Ollama: {e}", exc_info=True)
        return {"cpu": 0, "ram_percent": 0, "ram_gb": 0, "gpu_util": 0, "gpu_mem": 0}


def collect_metrics():
    """Фоновый сбор метрик в бесконечном цикле"""
    logger.info("=== Запуск фонового сбора метрик и управления ===")
    init_gpu()

    global last_cpu_stats
    last_cpu_stats = None

    iteration = 0
    while True:
        try:
            iteration += 1
            timestamp = datetime.now().isoformat()

            # 1. Read all GPU metrics in one pass
            sys_gpu_util_val = 0
            sys_gpu_mem_val = 0
            per_process = {}
            ollama_gpu_util_val = 0

            if NVIDIA_AVAILABLE and gpu_handles:
                total_util = 0
                total_mem_used = 0
                total_mem_total = 0

                for gpu_id, handle in enumerate(gpu_handles):
                    try:
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        total_util += util.gpu

                        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        total_mem_used += mem_info.used
                        total_mem_total += mem_info.total

                        samples = pynvml.nvmlDeviceGetProcessUtilization(handle, 0)
                        for sample in samples:
                            pid = sample.pid
                            if pid not in per_process:
                                per_process[pid] = {}
                            per_process[pid][gpu_id] = sample.smUtil
                    except Exception:
                        pass

                sys_gpu_util_val = total_util / gpu_count if gpu_count > 0 else 0
                sys_gpu_mem_val = (total_mem_used / total_mem_total * 100) if total_mem_total > 0 else 0

                ollama_pids = get_ollama_container_pids()
                ollama_gpu_util_val = compute_ollama_gpu_from_per_process(per_process, ollama_pids)

            # 2. Collect CPU/RAM via existing functions (GPU reads inside are redundant but harmless)
            sys_metrics = get_system_metrics()
            ollama_metrics = get_ollama_metrics()

            # 3. Override GPU with values from the single measurement pass
            sys_metrics["gpu_util"] = sys_gpu_util_val
            sys_metrics["gpu_mem"] = sys_gpu_mem_val
            ollama_metrics["gpu_util"] = ollama_gpu_util_val

            metrics["timestamps"].append(timestamp)
            for key in metrics["system"]:
                if key in sys_metrics:
                    metrics["system"][key].append(sys_metrics[key])
            for key in metrics["ollama"]:
                if key in ollama_metrics:
                    metrics["ollama"][key].append(ollama_metrics[key])

            if iteration % 3 == 0:
                sys_str = f"CPU={sys_metrics['cpu']:.1f}% RAM={sys_metrics['ram_percent']:.1f}%({sys_metrics['ram_gb']:.1f}GB) GPU={sys_metrics['gpu_util']:.1f}%({sys_metrics['gpu_mem']:.1f}% mem)"
                ollama_str = f"CPU={ollama_metrics['cpu']:.1f}% RAM={ollama_metrics['ram_percent']:.1f}%({ollama_metrics['ram_gb']:.1f}GB) GPU={ollama_metrics['gpu_util']:.1f}%({ollama_metrics['gpu_mem']:.1f}% mem)"
                logger.info(f"✅ Система: {sys_str} | Ollama: {ollama_str}")
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле: {e}", exc_info=True)

        time.sleep(UPDATE_INTERVAL)


@app.route("/")
def index():
    return render_template(
        "index.html",
        update_interval=UPDATE_INTERVAL * 1000,
        retention_minutes=RETENTION_TIME // 60,
    )


@app.route("/api/metrics")
def get_metrics_api():
    return jsonify(
        {
            "timestamps": list(metrics["timestamps"]),
            "system": {k: list(v) for k, v in metrics["system"].items()},
            "ollama": {k: list(v) for k, v in metrics["ollama"].items()},
        }
    )


@app.route("/api/system-info")
def get_system_info():
    """Возвращает информацию о системе"""
    global total_system_ram_gb, gpu_count, gpu_handles, NVIDIA_AVAILABLE

    cpu_cores = psutil.cpu_count()

    total_gpu_mem_gb = 0
    if NVIDIA_AVAILABLE and gpu_handles:
        for handle in gpu_handles:
            try:
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                total_gpu_mem_gb += mem_info.total / (1024**3)
            except Exception as e:
                logger.debug(f"Ошибка получения памяти GPU: {e}")

    return jsonify(
        {
            "success": True,
            "cpu_cores": cpu_cores,
            "total_ram_gb": round(total_system_ram_gb, 2),
            "total_gpus": gpu_count,
            "total_gpu_mem_gb": round(total_gpu_mem_gb, 2),
        }
    )


@app.route("/api/ollama/unload/<path:model>", methods=["POST"])
def unload_ollama_model(model):
    """Выгрузить модель из памяти Ollama через keep_alive=0"""
    try:
        req = urllib.request.Request(
            "http://ollama:11434/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            logger.info(f"✅ Модель {model} выгружена: {result}")
            return jsonify({"success": True, "model": model, "result": result})
    except Exception as e:
        logger.error(f"❌ Ошибка выгрузки модели {model}: {e}")
        return jsonify({"success": False, "model": model, "error": str(e)}), 500


@app.route("/api/ollama/unload-all", methods=["POST"])
def unload_all_ollama_models():
    """Выгрузить все модели из памяти Ollama"""
    try:
        req = urllib.request.Request("http://ollama:11434/api/ps")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        models = data.get("models", [])
        unloaded = []
        errors = []

        for m in models:
            try:
                model_name = m.get("name", "")
                if not model_name:
                    continue
                ureq = urllib.request.Request(
                    "http://ollama:11434/api/generate",
                    data=json.dumps({"model": model_name, "keep_alive": 0}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(ureq, timeout=30) as uresp:
                    json.loads(uresp.read().decode())
                unloaded.append(model_name)
                logger.info(f"✅ Модель {model_name} выгружена")
            except Exception as e:
                errors.append({"model": model_name, "error": str(e)})
                logger.error(f"❌ Ошибка выгрузки {model_name}: {e}")

        return jsonify(
            {
                "success": True,
                "unloaded": unloaded,
                "errors": errors,
                "total": len(models),
            }
        )
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка моделей: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ollama/models")
def get_ollama_models():
    """Получить список загруженных моделей Ollama"""
    try:
        req = urllib.request.Request("http://ollama:11434/api/ps")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        models = []
        for m in data.get("models", []):
            models.append(
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "size_formatted": m.get("size_formatted", ""),
                    "processor": m.get("details", {}).get("format", ""),
                    "family": m.get("details", {}).get("family", ""),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                    "quantization": m.get("details", {}).get("quantization_level", ""),
                }
            )

        # Проверяем, не загружается ли ещё модель (llama-server в процессе прогрева)
        loading = get_loading_model()
        if loading and not any(m["name"] == loading["name"] for m in models):
            models.append(loading)

        return jsonify({"success": True, "models": models, "count": len(models)})
    except Exception as e:
        logger.error(f"❌ Ошибка получения моделей: {e}")
        return jsonify({"success": False, "models": [], "count": 0, "error": str(e)})


def get_loading_model():
    """Определить модель, которая сейчас загружается (llama-server запущен, но /api/ps ещё пуст)"""
    try:
        result = subprocess.run(
            ["docker", "exec", "ollama", "ps", "aux"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        hex_hash = None
        for line in result.stdout.split("\n"):
            if "llama-server" in line and "--model" in line:
                m = re.search(r"--model\s+\S+/sha256-(\w+)", line)
                if m:
                    hex_hash = m.group(1)
                    break

        if not hex_hash:
            return None

        # Ищем в манифестах модель, использующую этот blob
        # В манифестах хеш записан как sha256:hex_hash
        grep = subprocess.run(
            ["docker", "exec", "ollama", "find",
             "/root/.ollama/models/manifests", "-type", "f",
             "-exec", "grep", "-l", hex_hash, "{}", "+"],
            capture_output=True, text=True, timeout=10,
        )

        name = None
        if grep.returncode == 0 and grep.stdout.strip():
            path = grep.stdout.strip().split("\n")[0]
            m = re.search(r"library/([^/]+)/([^/]+)$", path)
            if m:
                name = f"{m.group(1)}:{m.group(2)}"

        if not name:
            return {"name": f"sha256-{hex_hash}", "status": "loading", "size": 0}

        # Обогащаем данными из /api/tags (размер на диске, параметры, квантование)
        try:
            tags_req = urllib.request.Request("http://ollama:11434/api/tags")
            with urllib.request.urlopen(tags_req, timeout=10) as tags_resp:
                tags_data = json.loads(tags_resp.read().decode())
            for m in tags_data.get("models", []):
                if m.get("name") == name:
                    details = m.get("details", {})
                    return {
                        "name": name,
                        "status": "loading",
                        "size": m.get("size", 0),
                        "size_formatted": m.get("size", 0) > 0 and (
                            f"{m['size'] / 1073741824:.1f} GB" if m['size'] > 1073741824
                            else f"{m['size'] / 1048576:.0f} MB"
                        ) or "",
                        "processor": details.get("format", ""),
                        "family": details.get("family", ""),
                        "parameter_size": details.get("parameter_size", ""),
                        "quantization": details.get("quantization_level", ""),
                    }
        except Exception:
            pass

        return {"name": name, "status": "loading", "size": 0}
    except Exception as e:
        logger.error(f"❌ Ошибка определения загружаемой модели: {e}")
        return None


logger.info("=== ИНИЦИАЛИЗАЦИЯ ПАНЕЛИ УПРАВЛЕНИЯ ===")
logger.info(f"Общая RAM системы: {total_system_ram_gb:.1f} GB")
collector_thread = threading.Thread(target=collect_metrics, daemon=True)
collector_thread.start()
logger.info(f"Фоновый поток запущен: {collector_thread.is_alive()}")

if __name__ == "__main__":
    logger.info("🚀 Flask сервер запускается на порту 5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
