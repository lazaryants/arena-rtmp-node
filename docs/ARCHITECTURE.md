# Архитектура

## Медиатракт

1. Источник публикует RTMP в `placeN/streamN`.
2. Nginx-RTMP при включённом `publish_auth_enabled` вызывает локальный auth callback.
3. Nginx-RTMP режет принятый поток на live HLS без участия Python.
4. Restream Manager при необходимости запускает отдельный FFmpeg для каждого назначения с копированием кодеков.

Python-сервисы не находятся в основном пути RTMP → HLS. Их перезапуск не должен останавливать уже принятый Nginx поток.

## Компоненты

| Компонент | Назначение | Локальный порт |
|---|---|---:|
| Nginx-RTMP | RTMP ingest и HLS | 1935 |
| Nginx HTTPS | UI, API proxy, HLS | 443 |
| Restream Manager | конфигурация и FFmpeg процессы | 5000 |
| RTMP Auth | `on_publish` callback | 8080 |
| RTMP Stat | локальная XML-статистика | 8090 |

## Совместимость

Baseline сохраняет 16 фиксированных RTMP applications. Авторизацию следует включать по одной площадке после обновления URL на стороне соответствующего publisher.
