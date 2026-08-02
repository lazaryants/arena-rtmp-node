# Архитектура

## Медиатракт

1. Источник публикует RTMP в `placeN/streamN`.
2. Nginx-RTMP при включённом `publish_auth_enabled` вызывает локальный auth callback.
3. Nginx-RTMP режет принятый поток на live HLS без участия Python.
4. Restream Manager отправляет supervisor только действие и номера площадки/назначения.
5. Restream Supervisor читает destination из локальной конфигурации и владеет FFmpeg с копированием кодеков.

Python-сервисы не находятся в основном пути RTMP → HLS. Их перезапуск не должен останавливать уже принятый Nginx поток.

## Компоненты

| Компонент | Назначение | Локальный порт |
|---|---|---:|
| Nginx-RTMP | RTMP ingest и HLS | 1935 |
| Nginx HTTPS | UI, API proxy, HLS | 443 |
| Restream Manager | web API и конфигурация | 5000 |
| Restream Supervisor | процессы исходящих FFmpeg | Unix socket |
| RTMP Auth | `on_publish` callback | 8080 |
| RTMP Stat | локальная XML-статистика | 8090 |

Restream Manager работает через Gunicorn с одним `gthread` worker. Изменения конфигурации сериализуются файловой блокировкой. Supervisor работает отдельной systemd-службой и принимает по Unix-сокету только фиксированные команды и числовые идентификаторы. Поэтому перезапуск Gunicorn не останавливает активные исходящие FFmpeg.

## Node API

| Endpoint | Назначение |
|---|---|
| `/api/node/health` | config, FFmpeg, HLS root и доступность RTMP stat |
| `/api/node/metrics` | HLS-состояние, агрегаты RTMP/restream и ресурсы сервера |

API намеренно не возвращает ключи, source/destination URL, IP-адреса RTMP-клиентов или журналы. Во внешнем Nginx оба endpoint наследуют Basic Auth. Для интеграции с центральной платформой позже будет добавлена отдельная машинная авторизация.

## Совместимость

Baseline сохраняет 16 фиксированных RTMP applications. Авторизацию следует включать по одной площадке после обновления URL на стороне соответствующего publisher.
