#!/usr/bin/env python3
"""
DVR Recorder - записывает активные HLS потоки
"""
import os
import subprocess
import time
import json
import signal
import sys
from pathlib import Path
from datetime import datetime

HLS_BASE = "/var/www/hls"
DVR_BASE = "/var/www/dvr"
MAX_AGE_SECONDS = 30  # Поток активен если последний .ts файл моложе 30 секунд
SEGMENT_DURATION = 4  # Длительность сегмента в секундах
PLAYLIST_LENGTH = 900  # 1 час = 3600 секунд / 4 секунды = 900 сегментов

# Хранение активных процессов записи
recording_processes = {}

def is_stream_active(place_id):
    """Проверяет активность потока по наличию свежих .ts файлов"""
    hls_dir = Path(HLS_BASE) / f"place{place_id}"
    m3u8_file = hls_dir / f"stream{place_id}.m3u8"
    
    if not m3u8_file.exists():
        return False
    
    # Ищем самый свежий .ts файл
    ts_files = list(hls_dir.glob(f"stream{place_id}-*.ts"))
    if not ts_files:
        return False
    
    latest_ts = max(ts_files, key=os.path.getmtime)
    age = time.time() - os.path.getmtime(latest_ts)
    
    return age < MAX_AGE_SECONDS

def start_recording(place_id):
    """Запускает запись потока"""
    if place_id in recording_processes:
        return  # Уже записывается
    
    source_url = f"http://localhost/hls/place{place_id}/stream{place_id}.m3u8"
    output_dir = Path(DVR_BASE) / f"place{place_id}"
    output_pattern = str(output_dir / f"dvr_stream{place_id}_%Y%m%d_%H%M%S.ts")
    playlist_file = output_dir / f"dvr_stream{place_id}.m3u8"
    
    # Команда FFmpeg для записи HLS с плейлистом
    cmd = [
        '/usr/bin/ffmpeg',
        '-i', source_url,
        '-c', 'copy',
        '-map', '0',
        '-f', 'hls',
        '-hls_time', str(SEGMENT_DURATION),
        '-hls_list_size', str(PLAYLIST_LENGTH),
        '-hls_flags', 'delete_segments+append_list',
        '-hls_segment_filename', output_pattern,
        '-strftime', '1',
        str(playlist_file)
    ]
    
    try:
        # Запускаем процесс
        log_file = open(f"/var/log/dvr_recorder_place{place_id}.log", 'a')
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        
        recording_processes[place_id] = {
            'process': process,
            'started_at': datetime.now(),
            'log_file': log_file
        }
        
        print(f"[{datetime.now()}] Started recording place{place_id} (PID: {process.pid})")
        
    except Exception as e:
        print(f"[{datetime.now()}] Error starting recording for place{place_id}: {e}")

def stop_recording(place_id):
    """Останавливает запись потока"""
    if place_id not in recording_processes:
        return
    
    try:
        process_info = recording_processes[place_id]
        process = process_info['process']
        
        # Отправляем сигнал всей группе процессов
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)
        
        process_info['log_file'].close()
        del recording_processes[place_id]
        
        print(f"[{datetime.now()}] Stopped recording place{place_id}")
        
    except Exception as e:
        print(f"[{datetime.now()}] Error stopping recording for place{place_id}: {e}")

def cleanup_old_segments():
    """Удаляет сегменты старше 1 часа"""
    cutoff_time = time.time() - 3600  # 1 час назад
    
    for place_id in range(1, 17):
        dvr_dir = Path(DVR_BASE) / f"place{place_id}"
        if not dvr_dir.exists():
            continue
        
        # Удаляем старые .ts файлы
        for ts_file in dvr_dir.glob("dvr_*.ts"):
            if os.path.getmtime(ts_file) < cutoff_time:
                try:
                    os.remove(ts_file)
                except:
                    pass
        
        # Обновляем m3u8 плейлист (удаляем старые записи)
        m3u8_file = dvr_dir / f"dvr_stream{place_id}.m3u8"
        if m3u8_file.exists():
            try:
                with open(m3u8_file, 'r') as f:
                    lines = f.readlines()
                
                # Оставляем только последние 900 сегментов (1 час)
                new_lines = []
                segment_count = 0
                for line in lines:
                    if line.startswith('#EXTINF:'):
                        segment_count += 1
                        if segment_count > len(lines) - PLAYLIST_LENGTH:
                            new_lines.append(line)
                    elif line.strip() and not line.startswith('#'):
                        if segment_count > len(lines) - PLAYLIST_LENGTH:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
                
                with open(m3u8_file, 'w') as f:
                    f.writelines(new_lines)
                    
            except Exception as e:
                print(f"[{datetime.now()}] Error updating playlist for place{place_id}: {e}")

def main():
    """Основной цикл"""
    print(f"[{datetime.now()}] DVR Recorder started")
    
    while True:
        try:
            # Проверяем все 16 площадок
            for place_id in range(1, 17):
                is_active = is_stream_active(place_id)
                is_recording = place_id in recording_processes
                
                # Проверяем что процесс ещё жив
                if is_recording:
                    process = recording_processes[place_id]['process']
                    if process.poll() is not None:
                        # Процесс завершился
                        del recording_processes[place_id]
                        is_recording = False
                
                # Запускаем запись если поток активен и не записывается
                if is_active and not is_recording:
                    start_recording(place_id)
                
                # Останавливаем запись если поток не активен
                elif not is_active and is_recording:
                    stop_recording(place_id)
            
            # Очистка старых сегментов
            cleanup_old_segments()
            
            # Ждём 10 секунд перед следующей проверкой
            time.sleep(10)
            
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] Shutting down...")
            # Останавливаем все записи
            for place_id in list(recording_processes.keys()):
                stop_recording(place_id)
            break
        except Exception as e:
            print(f"[{datetime.now()}] Error in main loop: {e}")
            time.sleep(10)

if __name__ == '__main__':
    main()
