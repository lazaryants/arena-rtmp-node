#!/usr/bin/env python3
from flask import Flask, render_template, request, jsonify, redirect, url_for
import subprocess
import os
import signal
import json
import re
import time
import psutil
import secrets
from datetime import datetime
from functools import wraps

try:
    from .settings import SETTINGS
    from .monitoring import health_snapshot, metrics_snapshot
    from .config_store import ConfigStore, ConfigValidationError
except ImportError:
    from settings import SETTINGS
    from monitoring import health_snapshot, metrics_snapshot
    from config_store import ConfigStore, ConfigValidationError

app = Flask(
    __name__,
    template_folder=str(SETTINGS.template_dir),
)

# ===== КОНФИГУРАЦИЯ =====
CONFIG_FILE = SETTINGS.config_file
CONFIG_STORE = ConfigStore(CONFIG_FILE)

RTMP_URL_PATTERN = re.compile(
    r"rtmps?://\S+",
    re.IGNORECASE,
)


@app.route('/api/node/health')
def api_node_health():
    """Safe component readiness without secrets."""
    return jsonify(health_snapshot(SETTINGS))


@app.route('/api/node/metrics')
def api_node_metrics():
    """Safe node metrics without URLs, keys, client addresses or logs."""
    try:
        return jsonify(metrics_snapshot(SETTINGS))
    except (OSError, ValueError, json.JSONDecodeError):
        return jsonify({
            'status': 'unavailable',
            'message': 'Node metrics are temporarily unavailable',
        }), 503


@app.errorhandler(ConfigValidationError)
def handle_invalid_stored_config(error):
    """Do not expose config contents when the stored file is invalid."""
    return jsonify({
        'success': False,
        'message': 'Node configuration is invalid',
    }), 503


def redact_rtmp_urls(value):
    """Удаляет RTMP URL и ключи из диагностики."""
    return RTMP_URL_PATTERN.sub(
        "[RTMP URL REDACTED]",
        str(value),
    )



def load_config():
    """Load and validate the complete node configuration."""
    return CONFIG_STORE.load()

def save_config(config):
    """Validate and atomically replace the node configuration."""
    return CONFIG_STORE.save(config)


def serialized_config_write(function):
    """Prevent concurrent admin requests from losing configuration updates."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with CONFIG_STORE.locked():
            return function(*args, **kwargs)
    return wrapped

def get_process_status(pid_file):
    """Проверяет статус процесса по PID файлу"""
    if not os.path.exists(pid_file):
        return {'status': 'stopped', 'pid': None, 'uptime': 0}
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        process = psutil.Process(pid)
        if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
            create_time = process.create_time()
            uptime = int(time.time() - create_time)
            cpu_percent = process.cpu_percent(interval=0.1)
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            return {
                'status': 'running',
                'pid': pid,
                'uptime': uptime,
                'cpu': cpu_percent,
                'memory': round(memory_mb, 2)
            }
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        if os.path.exists(pid_file):
            os.remove(pid_file)
    
    return {'status': 'stopped', 'pid': None, 'uptime': 0}

def get_delay_info(log_file):
    """Анализирует логи на предмет задержки"""
    if not os.path.exists(log_file):
        return {'delay': 0, 'drops': 0, 'errors': []}
    
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()[-100:]
        
        drops = 0
        errors = []
        
        for line in lines:
            if 'drop' in line.lower():
                drops += 1
            if 'error' in line.lower() or 'failed' in line.lower():
                errors.append(
                    redact_rtmp_urls(
                        line.strip()
                    )
                )
        
        return {
            'drops': drops,
            'errors': errors[-5:]
        }
    except Exception:
        return {'drops': 0, 'errors': []}

def get_fields():
    """Получает список полей для рестрима из конфига"""
    config = load_config()
    fields = {}
    for field_id, field_data in config.get('fields', {}).items():
        # Миграция: если есть старый restream_url, преобразуем в список
        urls = field_data.get('restream_urls', [])
        if not urls and field_data.get('restream_url'):
            urls = [field_data['restream_url']]
        
        # Получаем stream key (по умолчанию stream{id})
        stream_key = field_data.get('stream_key', f'stream{field_id}')
        
        fields[int(field_id)] = {
            'name': field_data.get('name', f'Field {field_id}'),
            'source': f'{SETTINGS.local_hls_origin}/place{field_id}/{stream_key}.m3u8',
            'urls': urls,
            'pid_files': [str(SETTINGS.pid_file(field_id, i)) for i in range(len(urls))],
            'log_files': [str(SETTINGS.log_file(field_id, i)) for i in range(len(urls))]
        }
    return fields

def start_restream(field_id, url_index=None):
    """Запускает рестрим для указанного поля (одного URL или всех)"""
    try:
        SETTINGS.ensure_runtime_directories()
        fields = get_fields()
        
        if field_id not in fields:
            return False, "Invalid field ID"
        
        field = fields[field_id]
        
        if not field['urls']:
            return False, "No URLs configured"
        
        # Определяем какие URL запускать
        if url_index is not None:
            if url_index >= len(field['urls']):
                return False, "Invalid URL index"
            urls_to_start = [(url_index, field['urls'][url_index])]
        else:
            urls_to_start = list(enumerate(field['urls']))
        
        started = []
        
        for idx, url in urls_to_start:
            if not url:
                continue
            
            pid_file = SETTINGS.pid_file(field_id, idx)
            log_file = SETTINGS.log_file(field_id, idx)
            
            # Проверяем что уже не запущен
            status = get_process_status(pid_file)
            if status['status'] == 'running':
                continue
            
            # Команда FFmpeg
            cmd = [
                str(SETTINGS.ffmpeg_bin),
                '-hide_banner',
                '-loglevel', 'warning',
                '-nostats',
                '-i', field['source'],
                '-c', 'copy',
                '-f', 'flv',
                '-flvflags', 'no_duration_filesize',
                url
            ]

            # Создаём журнал сразу с правами 600.
            log_fd = os.open(
                log_file,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_APPEND,
                0o600,
            )
            os.chmod(log_file, 0o600)

            log_fh = os.fdopen(
                log_fd,
                'a',
                encoding='utf-8',
                buffering=1,
            )

            try:
                log_fh.write(
                    f"\n=== Restream started at "
                    f"{datetime.now()} ===\n"
                )
                log_fh.write(
                    f"Source: {field['source']}\n"
                )
                log_fh.write(
                    "Destination: [configured]\n"
                )
                log_fh.flush()

                process = subprocess.Popen(
                    cmd,
                    stdout=log_fh,
                    stderr=log_fh,
                    stdin=subprocess.DEVNULL,
                    bufsize=0,
                )
            finally:
                # FFmpeg уже получил собственные
                # stdout/stderr descriptors.
                log_fh.close()

            # Сохраняем PID.
            with open(pid_file, 'w') as f:
                f.write(str(process.pid))

            started.append(f"URL #{idx+1} (PID: {process.pid})")
        
        if started:
            return True, f"Started: {', '.join(started)}"
        else:
            return False, "Nothing to start (all already running)"
            
    except Exception as e:
        import traceback
        return False, f"Error: {str(e)}"


def stop_restream(field_id, url_index=None):
    """Останавливает рестрим для указанного поля (одного URL или всех)"""
    try:
        fields = get_fields()
        
        if field_id not in fields:
            return False, "Invalid field ID"
        
        field = fields[field_id]
        
        # Определяем какие URL останавливать
        if url_index is not None:
            indices = [url_index]
        else:
            indices = list(range(len(field['urls'])))
        
        stopped = []
        
        for idx in indices:
            pid_file = SETTINGS.pid_file(field_id, idx)
            status = get_process_status(pid_file)
            
            if status['status'] != 'running':
                continue
            
            try:
                process = psutil.Process(status['pid'])
                process.terminate()
                process.wait(timeout=5)
                
                if os.path.exists(pid_file):
                    os.remove(pid_file)
                
                stopped.append(f"URL #{idx+1}")
            except Exception as e:
                pass
        
        if stopped:
            return True, f"Stopped: {', '.join(stopped)}"
        else:
            return False, "Nothing to stop"
            
    except Exception as e:
        return False, f"Error: {str(e)}"


# ===== СТРАНИЦЫ =====

@app.route('/')
def index():
    """Главная страница с панелью управления"""
    fields = get_fields()
    fields_status = {}
    
    for field_id, field in fields.items():
        # Статусы для каждого URL
        url_statuses = []
        for idx, url in enumerate(field['urls']):
            pid_file = SETTINGS.pid_file(field_id, idx)
            log_file = SETTINGS.log_file(field_id, idx)
            status = get_process_status(pid_file)
            delay_info = get_delay_info(log_file)
            url_statuses.append({
                'url': url,
                'index': idx,
                'status': status,
                'delay_info': delay_info
            })
        
        # Общий статус поля
        running_count = sum(1 for s in url_statuses if s['status']['status'] == 'running')
        
        fields_status[field_id] = {
            'name': field['name'],
            'urls': url_statuses,
            'running_count': running_count,
            'total_count': len(url_statuses)
        }
    
    return render_template('index.html', fields=fields_status)


# ===== RESTREAM API =====

@app.route('/api/start/<int:field_id>', methods=['POST'])
def api_start_all(field_id):
    """API: запустить рестрим для ВСЕХ URL поля"""
    success, message = start_restream(field_id, url_index=None)
    return jsonify({'success': success, 'message': message})


@app.route('/api/start/<int:field_id>/<int:url_index>', methods=['POST'])
def api_start_specific(field_id, url_index):
    """API: запустить рестрим для конкретного URL"""
    success, message = start_restream(field_id, url_index)
    return jsonify({'success': success, 'message': message})


@app.route('/api/stop/<int:field_id>', methods=['POST'])
def api_stop_all(field_id):
    """API: остановить рестрим для ВСЕХ URL поля"""
    success, message = stop_restream(field_id, url_index=None)
    return jsonify({'success': success, 'message': message})


@app.route('/api/stop/<int:field_id>/<int:url_index>', methods=['POST'])
def api_stop_specific(field_id, url_index):
    """API: остановить рестрим для конкретного URL"""
    success, message = stop_restream(field_id, url_index)
    return jsonify({'success': success, 'message': message})


@app.route('/api/restart/<int:field_id>', methods=['POST'])
def api_restart_all(field_id):
    """API: перезапустить рестрим для ВСЕХ URL поля"""
    stop_restream(field_id, url_index=None)
    time.sleep(1)
    success, message = start_restream(field_id, url_index=None)
    return jsonify({'success': success, 'message': message})


@app.route('/api/restart/<int:field_id>/<int:url_index>', methods=['POST'])
def api_restart_specific(field_id, url_index):
    """API: перезапустить рестрим для конкретного URL"""
    stop_restream(field_id, url_index)
    time.sleep(1)
    success, message = start_restream(field_id, url_index)
    return jsonify({'success': success, 'message': message})


@app.route('/api/logs/<int:field_id>/<int:url_index>')
def api_logs_specific(field_id, url_index):
    """API: получить логи для конкретного URL"""
    log_file = SETTINGS.log_file(field_id, url_index)
    if not os.path.exists(log_file):
        return jsonify({'logs': []})
    
    try:
        with open(log_file, 'r') as f:
            lines = [
                redact_rtmp_urls(line)
                for line in f.readlines()[-50:]
            ]
        return jsonify({'logs': lines})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===== RESTREAM URLS API =====

@app.route('/api/restream-urls/<int:field_id>', methods=['GET'])
@serialized_config_write
def api_get_restream_urls(field_id):
    """API: получить список URL для рестрима"""
    config = load_config()
    
    if str(field_id) not in config.get('fields', {}):
        return jsonify({'success': False, 'message': 'Field not found'}), 404
    
    field = config['fields'][str(field_id)]
    
    # Миграция
    urls = field.get('restream_urls', [])
    if not urls and field.get('restream_url'):
        urls = [field['restream_url']]
        field['restream_urls'] = urls
        if 'restream_url' in field:
            del field['restream_url']
        save_config(config)
    
    return jsonify({'success': True, 'urls': urls})


@app.route('/api/restream-urls/<int:field_id>', methods=['POST'])
@serialized_config_write
def api_add_restream_url(field_id):
    """API: добавить новый URL для рестрима"""
    try:
        data = request.get_json()
        new_url = data.get('url', '').strip()
        
        if not new_url:
            return jsonify({'success': False, 'message': 'URL is empty'}), 400
        
        config = load_config()
        
        if str(field_id) not in config.get('fields', {}):
            return jsonify({'success': False, 'message': 'Field not found'}), 404
        
        field = config['fields'][str(field_id)]
        
        # Миграция
        if 'restream_urls' not in field:
            field['restream_urls'] = []
            if field.get('restream_url'):
                field['restream_urls'].append(field['restream_url'])
                del field['restream_url']
        
        field['restream_urls'].append(new_url)
        save_config(config)
        
        return jsonify({
            'success': True,
            'message': 'URL added',
            'index': len(field['restream_urls']) - 1
        })
    except ConfigValidationError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/restream-urls/<int:field_id>/<int:url_index>', methods=['PUT'])
@serialized_config_write
def api_update_restream_url(field_id, url_index):
    """API: обновить URL для рестрима"""
    try:
        data = request.get_json()
        new_url = data.get('url', '').strip()
        
        config = load_config()
        
        if str(field_id) not in config.get('fields', {}):
            return jsonify({'success': False, 'message': 'Field not found'}), 404
        
        field = config['fields'][str(field_id)]
        
        # Миграция
        if 'restream_urls' not in field:
            field['restream_urls'] = []
            if field.get('restream_url'):
                field['restream_urls'].append(field['restream_url'])
                del field['restream_url']
        
        if url_index >= len(field['restream_urls']):
            return jsonify({'success': False, 'message': 'Invalid URL index'}), 400
        
        # Останавливаем рестрим для этого URL если он запущен
        pid_file = SETTINGS.pid_file(field_id, url_index)
        status = get_process_status(pid_file)
        if status['status'] == 'running':
            try:
                process = psutil.Process(status['pid'])
                process.terminate()
                process.wait(timeout=5)
                if os.path.exists(pid_file):
                    os.remove(pid_file)
            except:
                pass
        
        field['restream_urls'][url_index] = new_url
        save_config(config)
        
        return jsonify({'success': True, 'message': 'URL updated'})
    except ConfigValidationError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/restream-urls/<int:field_id>/<int:url_index>', methods=['DELETE'])
@serialized_config_write
def api_delete_restream_url(field_id, url_index):
    """API: удалить URL для рестрима"""
    try:
        config = load_config()
        
        if str(field_id) not in config.get('fields', {}):
            return jsonify({'success': False, 'message': 'Field not found'}), 404
        
        field = config['fields'][str(field_id)]
        
        # Миграция
        if 'restream_urls' not in field:
            field['restream_urls'] = []
            if field.get('restream_url'):
                field['restream_urls'].append(field['restream_url'])
                del field['restream_url']
        
        if url_index >= len(field['restream_urls']):
            return jsonify({'success': False, 'message': 'Invalid URL index'}), 400
        
        # Останавливаем рестрим если запущен
        pid_file = SETTINGS.pid_file(field_id, url_index)
        status = get_process_status(pid_file)
        if status['status'] == 'running':
            try:
                process = psutil.Process(status['pid'])
                process.terminate()
                process.wait(timeout=5)
                if os.path.exists(pid_file):
                    os.remove(pid_file)
            except:
                pass
        
        # Удаляем URL
        field['restream_urls'].pop(url_index)
        
        # Переименовываем PID и лог файлы для оставшихся URL
        for i in range(url_index, len(field['restream_urls'])):
            old_pid = SETTINGS.pid_file(field_id, i + 1)
            new_pid = SETTINGS.pid_file(field_id, i)
            old_log = SETTINGS.log_file(field_id, i + 1)
            new_log = SETTINGS.log_file(field_id, i)
            
            if os.path.exists(old_pid):
                os.rename(old_pid, new_pid)
            if os.path.exists(old_log):
                os.rename(old_log, new_log)
        
        save_config(config)
        
        return jsonify({'success': True, 'message': 'URL deleted'})
    except ConfigValidationError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ===== КОНФИГУРАЦИЯ ПОЛЕЙ =====

@app.route('/config/')
def config_page():
    """Страница конфигурации полей"""
    config = load_config()
    return render_template('config.html', fields=config.get('fields', {}))


@app.route('/api/config/fields')
def api_config_fields():
    """API: безопасный список включённых площадок для страницы мониторинга."""
    config = load_config()

    # Публичное представление строится только по белому списку.
    # Сюда нельзя добавлять key, restream_url, restream_urls
    # и другие конфигурационные или секретные значения.
    enabled_fields = {}

    for field_id, field in config.get('fields', {}).items():
        if not field.get('enabled', False):
            continue

        stream_key = field.get('stream_key') or f'stream{field_id}'

        enabled_fields[field_id] = {
            'name': field.get('name') or f'Площадка {field_id}',
            'emoji': field.get('emoji') or '🏟️',
            'rtmp_url': (
                f'rtmp://{SETTINGS.public_host}/'
                f'place{field_id}/{stream_key}'
            ),
            'hls_url': f'/hls/place{field_id}/{stream_key}.m3u8',
        }

    return jsonify(enabled_fields)


@app.route('/api/config/fields/status')
def api_config_fields_status():
    """API: проверить активность всех 16 площадок"""
    import glob
    
    config = load_config()
    status = {}
    now = time.time()
    
    for i in range(1, 17):
        # Получаем stream key для этой площадки
        field_data = config.get('fields', {}).get(str(i), {})
        stream_key = field_data.get('stream_key', f'stream{i}')
        
        place_dir = SETTINGS.hls_root / f"place{i}"
        m3u8_file = f"{place_dir}/{stream_key}.m3u8"
        
        if not os.path.exists(m3u8_file):
            status[str(i)] = 'no_signal'
            continue
        
        ts_files = glob.glob(f"{place_dir}/{stream_key}-*.ts")
        if not ts_files:
            status[str(i)] = 'no_signal'
            continue
        
        latest_ts = max(ts_files, key=os.path.getmtime)
        age = now - os.path.getmtime(latest_ts)
        
        if age < 30:
            status[str(i)] = 'active'
        elif age < 120:
            status[str(i)] = 'stale'
        else:
            status[str(i)] = 'no_signal'
    
    return jsonify(status)


@app.route('/api/config/fields/all')
def api_config_fields_all():
    """API: получить все поля (для страницы конфигурации)"""
    config = load_config()
    
    # Добавляем stream_key и формируем URL динамически
    all_fields = {}
    for k, v in config.get('fields', {}).items():
        field_copy = v.copy()
        stream_key = v.get('stream_key', f'stream{k}')
        field_copy['rtmp_url'] = f"rtmp://{SETTINGS.public_host}/place{k}/{stream_key}"
        field_copy['hls_url'] = f"/hls/place{k}/{stream_key}.m3u8"
        field_copy['stream_key'] = stream_key
        all_fields[k] = field_copy
    
    return jsonify(all_fields)


@app.route('/api/config/fields', methods=['POST'])
@serialized_config_write
def api_config_create_field():
    """API: создать новое поле (использует слоты 1-16)"""
    try:
        data = request.get_json()
        config = load_config()
        
        existing_ids = [int(k) for k in config.get('fields', {}).keys()]
        free_slot = None
        for i in range(1, 17):
            if i not in existing_ids:
                free_slot = i
                break
        
        if free_slot is None:
            return jsonify({'success': False, 'message': 'All 16 slots are used!'}), 400
        
        new_id = str(free_slot)
        random_key = secrets.token_urlsafe(8)
        stream_key = data.get('stream_key', f'stream{new_id}').strip()
        
        if not stream_key:
            stream_key = f'stream{new_id}'
        
        config['fields'][new_id] = {
            'name': data.get('name', f'Field {new_id}'),
            'emoji': data.get('emoji', '🏟️'),
            'stream_key': stream_key,
            'rtmp_url': f"rtmp://{SETTINGS.public_host}/place{new_id}/{stream_key}",
            'hls_url': f"/hls/place{new_id}/{stream_key}.m3u8",
            'enabled': data.get('enabled', True),
            'key': random_key
        }
        
        save_config(config)
        return jsonify({'success': True, 'id': new_id, 'message': f'Field created in slot {new_id}'})
    except ConfigValidationError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/config/fields/<field_id>', methods=['PUT'])
@serialized_config_write
def api_config_update_field(field_id):
    """API: обновить поле"""
    try:
        data = request.get_json()
        config = load_config()
        
        if field_id not in config.get('fields', {}):
            return jsonify({'success': False, 'message': 'Field not found'}), 404
        
        field = config['fields'][field_id]
        
        if 'name' in data:
            field['name'] = data['name']
        if 'emoji' in data:
            field['emoji'] = data['emoji']
        if 'enabled' in data:
            field['enabled'] = data['enabled']
        if 'key' in data:
            field['key'] = data['key']
        
        # Обновляем stream_key если передан
        if 'stream_key' in data:
            new_stream_key = data['stream_key'].strip()
            if new_stream_key:
                old_stream_key = field.get('stream_key', f'stream{field_id}')
                
                # Если stream_key изменился, обновляем URL
                if new_stream_key != old_stream_key:
                    field['stream_key'] = new_stream_key
                    field['rtmp_url'] = f"rtmp://{SETTINGS.public_host}/place{field_id}/{new_stream_key}"
                    field['hls_url'] = f"/hls/place{field_id}/{new_stream_key}.m3u8"
        
        save_config(config)
        return jsonify({'success': True, 'message': 'Field updated'})
    except ConfigValidationError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/config/fields/<field_id>', methods=['DELETE'])
@serialized_config_write
def api_config_delete_field(field_id):
    """API: удалить поле"""
    try:
        config = load_config()
        
        if field_id not in config.get('fields', {}):
            return jsonify({'success': False, 'message': 'Field not found'}), 404
        
        del config['fields'][field_id]
        save_config(config)
        return jsonify({'success': True, 'message': 'Field deleted'})
    except ConfigValidationError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
