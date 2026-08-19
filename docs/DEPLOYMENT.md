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
| корень проекта | `/opt/arena-rtmp-node` |
| Python environment | `/opt/arena-rtmp-node/.venv` |
| параметры узла | `/opt/arena-rtmp-node/config/node.env` |
| изменяемая конфигурация | `/opt/arena-rtmp-node/state/restream-config.json` |
| PID-файлы | `/opt/arena-rtmp-node/run` |
| журналы ретрансляций | `/opt/arena-rtmp-node/logs` |
| Unix socket supervisor | `/opt/arena-rtmp-node/run/supervisor.sock` |
| HLS | `/var/www/hls` |

Основной путь задаётся через `ARENA_RTMP_ROOT`. Остальные значения можно переопределить в `config/node.env`; unit-файлы менять для этого не требуется.

Restream Manager запускается через Gunicorn на `127.0.0.1:5000`. Исходящими FFmpeg владеет отдельная служба `arena-restream-supervisor`, с которой manager связывается через локальный Unix-сокет.

Все три Python-службы запускаются от системного пользователя `arena-rtmp`. Код, `.venv` и `config/` остаются root-owned и доступны только для чтения. Manager может изменять только `state/`, supervisor — только `logs/` и `run/`, а auth callback не имеет writable-исключений.

Repository units должны проходить read-only аудит с exposure не выше `3.0`:

```bash
python3 scripts/audit_systemd.py --max-exposure 3.0
```

## Доменные имена

Основное предлагаемое имя узла — `rtmp.arena76.top`. Оно может одновременно использоваться для RTMP-публикации и web-интерфейса: протоколы работают на разных портах.

Если web-интерфейсу понадобится отдельное имя, например `node.arena-stream.icu`, его можно добавить в `server_name` Nginx и в TLS-сертификат. Python-код менять для этого не требуется. Значение `ARENA_RTMP_PUBLIC_HOST` определяет только адрес, который показывается пользователю как RTMP ingest URL.

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

### Активация RTMP-конфигурации

Входящие RTMP-публикации являются долгоживущими соединениями. Обычный `nginx reload` оставляет их на старом worker в состоянии `shutting down`; новый worker может вернуть пустую RTMP-stat статистику, хотя HLS продолжит обновляться. Core-директива `worker_shutdown_timeout` не обеспечивает закрытие таких соединений в используемом `nginx-rtmp-module`.

После установки или изменения RTMP-фрагмента следует использовать согласованное короткое окно и полный restart:

```bash
sudo nginx -t
sudo systemctl restart nginx
```

Камеры или другие publishers должны автоматически переподключиться. После restart необходимо проверить число соединений на порту 1935 и RTMP-stat. Для изменений только Python-приложения перезапуск Nginx не требуется.

## Обязательные меры

Сначала можно выполнить read-only проверку зависимостей:

```bash
sudo ./scripts/install.sh check
```

Для новой установки в пустой целевой каталог:

```bash
sudo ./scripts/install.sh install
```

Installer откажется перезаписывать существующий `/opt/arena-rtmp-node`.

## Обновление управляемой установки

Сначала выполнить полностью read-only preflight из отдельной копии нового release:

```bash
sudo ./scripts/update.sh check
```

Он проверяет marker управляемой установки, Python-код, JSON-пример, текущие зависимости и возможность migration рабочей конфигурации. Для применения требуется буквальное подтверждение:

```bash
sudo ./scripts/update.sh apply --confirm UPDATE
```

Updater:

- блокирует параллельный update;
- создаёт уникальный backup в `/var/backups/arena-rtmp-node/` с закрытыми правами;
- сохраняет managed-код, приватный `node.env`, state и установленные unit-файлы;
- останавливает только три Python-службы, но не Nginx;
- выполняет versioned migration конфигурации;
- обновляет код и generic systemd units, сохраняя private Nginx profile;
- проверяет установленный код и JSON до запуска;
- возвращает прежние файлы, state и units при любой ошибке;
- после запуска проверяет локальный health endpoint manager.

На время update исходящие FFmpeg-рестримы будут остановлены. Уже принятые Nginx RTMP/HLS-потоки продолжают работать, однако новый publisher с включённым `on_publish` не сможет подключиться, пока auth-служба остановлена. Поэтому production update выполняется только в согласованное окно. Скрипт не изменяет Nginx, DNS, TLS, HLS, журналы и PID-файлы и не обновляет Python-пакеты автоматически.

## Ротация журналов исходящих рестримов

FFmpeg держит файлы `logs/restream_field*.log` открытыми всё время работы рестрима. Поэтому правило использует `copytruncate`: журнал копируется и очищается без остановки процесса и без необходимости переоткрывать файловый дескриптор.

Установить repository-owned правило и проверить общую конфигурацию:

```bash
sudo install -o root -g root -m 0644 \
    /opt/arena-rtmp-node/logrotate/arena-rtmp-node \
    /etc/logrotate.d/arena-rtmp-node
sudo logrotate --debug /etc/logrotate.conf
```

Правило применяется только к `restream_field*.log`, ежедневно сохраняет до 14 архивов и досрочно ограничивает активный журнал размером 10 MiB. Audit-журнал управляет своей ротацией самостоятельно и этим правилом не затрагивается.

## Версия конфигурации

Новая установка использует `schema_version: 1`. Проверить старый рабочий файл без изменений:

```bash
sudo -u arena-rtmp \
    /opt/arena-rtmp-node/.venv/bin/python \
    /opt/arena-rtmp-node/scripts/migrate_config.py \
    --config /opt/arena-rtmp-node/state/restream-config.json
```

Код возврата `2` означает, что migration требуется. Для применения необходимо остановить manager, auth и supervisor, выполнить ту же команду с `--apply`, проверить созданный backup и только затем запускать службы. Команда не печатает ключи или destination URL, создаёт backup с режимом `600` и атомарно заменяет рабочий JSON. Автоматически выполнять migration при обычном запуске служб запрещено.

1. Скопировать `config/node.env.example` в `config/node.env` и проверить параметры узла.
2. Скопировать versioned `config/restream-config.example.json` в `state/restream-config.json` и заменить все ключи.
3. Проверить владельцев и права: `node.env` — `root:arena-rtmp`/`640`, рабочий JSON — `arena-rtmp:arena-rtmp`/`600`.
4. Настроить DNS, список `server_name` и TLS-пути в Nginx.
5. Защитить административные маршруты Basic Auth.
6. Выполнить `nginx -t` до reload.
7. Включать `on_publish` по одной неактивной площадке и проверять неправильный и правильный ключ реальной RTMP-публикацией.

Нельзя заменять конфигурацию действующего сервера напрямую файлами из репозитория без предварительного diff и резервной копии.
