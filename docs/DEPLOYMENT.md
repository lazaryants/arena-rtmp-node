# Развёртывание

Документ фиксирует текущую схему установки. Автоматический installer появится после стабилизации структуры.

## Требования

- Ubuntu 24.04;
- Nginx и `libnginx-mod-rtmp`;
- FFmpeg;
- Python 3.12 и `venv`;
- TLS-сертификат;
- файл Basic Auth `/etc/nginx/.htpasswd`.

## Пути по умолчанию

| Назначение | Путь |
|---|---|
| корень проекта | `/opt/cricket-rtmp-node` |
| Python environment | `/opt/cricket-rtmp-node/.venv` |
| параметры узла | `/opt/cricket-rtmp-node/config/node.env` |
| секретная конфигурация | `/opt/cricket-rtmp-node/config/restream-config.json` |
| PID-файлы | `/opt/cricket-rtmp-node/run` |
| журналы ретрансляций | `/opt/cricket-rtmp-node/logs` |
| HLS | `/var/www/hls` |

Основной путь задаётся через `CRICKET_RTMP_ROOT`. Остальные значения можно переопределить в `config/node.env`; unit-файлы менять для этого не требуется.

## Доменные имена

Основное предлагаемое имя узла — `rtmp.cricket-stream.icu`. Оно может одновременно использоваться для RTMP-публикации и web-интерфейса: протоколы работают на разных портах.

Если web-интерфейсу понадобится отдельное имя, например `node.cricket-stream.icu`, его можно добавить в `server_name` Nginx и в TLS-сертификат. Python-код менять для этого не требуется. Значение `CRICKET_RTMP_PUBLIC_HOST` определяет только адрес, который показывается пользователю как RTMP ingest URL.

## Обязательные меры

1. Скопировать `config/node.env.example` в `config/node.env` и проверить параметры узла.
2. Скопировать `config/restream-config.example.json` в `config/restream-config.json` и заменить все ключи.
3. Установить владельца `root:root` и режим `600` для обоих реальных конфигурационных файлов.
4. Настроить DNS, список `server_name` и TLS-пути в Nginx.
5. Защитить административные маршруты Basic Auth.
6. Выполнить `nginx -t` до reload.
7. Включать `on_publish` по одной неактивной площадке и проверять неправильный и правильный ключ реальной RTMP-публикацией.

Нельзя заменять конфигурацию действующего сервера напрямую файлами из репозитория без предварительного diff и резервной копии.
