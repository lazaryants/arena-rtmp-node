# Развёртывание

Документ фиксирует текущую схему установки. Первичный безопасный installer подготавливает файлы приложения, но не активирует системные конфигурации.

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
| изменяемая конфигурация | `/opt/cricket-rtmp-node/state/restream-config.json` |
| PID-файлы | `/opt/cricket-rtmp-node/run` |
| журналы ретрансляций | `/opt/cricket-rtmp-node/logs` |
| Unix socket supervisor | `/opt/cricket-rtmp-node/run/supervisor.sock` |
| HLS | `/var/www/hls` |

Основной путь задаётся через `CRICKET_RTMP_ROOT`. Остальные значения можно переопределить в `config/node.env`; unit-файлы менять для этого не требуется.

Restream Manager запускается через Gunicorn на `127.0.0.1:5000`. Исходящими FFmpeg владеет отдельная служба `cricket-restream-supervisor`, с которой manager связывается через локальный Unix-сокет.

Все три Python-службы запускаются от системного пользователя `cricket-rtmp`. Код, `.venv` и `config/` остаются root-owned и доступны только для чтения. Manager может изменять только `state/`, supervisor — только `logs/` и `run/`, а auth callback не имеет writable-исключений.

## Доменные имена

Основное предлагаемое имя узла — `rtmp.cricket-stream.icu`. Оно может одновременно использоваться для RTMP-публикации и web-интерфейса: протоколы работают на разных портах.

Если web-интерфейсу понадобится отдельное имя, например `node.cricket-stream.icu`, его можно добавить в `server_name` Nginx и в TLS-сертификат. Python-код менять для этого не требуется. Значение `CRICKET_RTMP_PUBLIC_HOST` определяет только адрес, который показывается пользователю как RTMP ingest URL.

## Генерация Nginx-конфигурации

Профиль конкретного сервера не хранится в Git:

```bash
cp config/nginx-render.example.json config/nginx-render.json
chmod 600 config/nginx-render.json
python3 scripts/render_nginx.py \
    --profile config/nginx-render.json \
    --output-dir build/nginx
```

Renderer создаёт только staging-файлы и ничего не устанавливает. Перед применением их необходимо сравнить с действующей конфигурацией. RTMP-фрагмент подключается на корневом уровне `nginx.conf`, HTTP и stat-фрагменты — внутри `http` через стандартный `conf.d`.

## Обязательные меры

Сначала можно выполнить read-only проверку зависимостей:

```bash
sudo ./scripts/install.sh check
```

Для новой установки в пустой целевой каталог:

```bash
sudo ./scripts/install.sh install
```

Installer откажется перезаписывать существующий `/opt/cricket-rtmp-node`. Обновление действующего узла будет реализовано отдельным скриптом с резервной копией и rollback.

## Версия конфигурации

Новая установка использует `schema_version: 1`. Проверить старый рабочий файл без изменений:

```bash
sudo -u cricket-rtmp \
    /opt/cricket-rtmp-node/.venv/bin/python \
    /opt/cricket-rtmp-node/scripts/migrate_config.py \
    --config /opt/cricket-rtmp-node/state/restream-config.json
```

Код возврата `2` означает, что migration требуется. Для применения необходимо остановить manager, auth и supervisor, выполнить ту же команду с `--apply`, проверить созданный backup и только затем запускать службы. Команда не печатает ключи или destination URL, создаёт backup с режимом `600` и атомарно заменяет рабочий JSON. Автоматически выполнять migration при обычном запуске служб запрещено.

1. Скопировать `config/node.env.example` в `config/node.env` и проверить параметры узла.
2. Скопировать versioned `config/restream-config.example.json` в `state/restream-config.json` и заменить все ключи.
3. Проверить владельцев и права: `node.env` — `root:cricket-rtmp`/`640`, рабочий JSON — `cricket-rtmp:cricket-rtmp`/`600`.
4. Настроить DNS, список `server_name` и TLS-пути в Nginx.
5. Защитить административные маршруты Basic Auth.
6. Выполнить `nginx -t` до reload.
7. Включать `on_publish` по одной неактивной площадке и проверять неправильный и правильный ключ реальной RTMP-публикацией.

Нельзя заменять конфигурацию действующего сервера напрямую файлами из репозитория без предварительного diff и резервной копии.
