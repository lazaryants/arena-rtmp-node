# cricket-rtmp-node

Узел приёма RTMP, раздачи HLS и ретрансляции потоков для Cricket Stream Platform.

Проект собран из проверенной конфигурации действующего RTMP-узла. Первый baseline намеренно сохраняет существующую схему `place1`–`place16` и передачу медиапотока без перекодирования.

## Возможности

- приём RTMP в 16 изолированных приложений Nginx-RTMP;
- формирование live HLS;
- опциональная авторизация публикации отдельно для каждой площадки;
- несколько исходящих RTMP-ретрансляций через FFmpeg с `-c copy`;
- административный web-интерфейс;
- production-запуск Restream Manager через Gunicorn;
- отдельный непривилегированный service user и systemd sandbox;
- локальная XML-статистика Nginx-RTMP на `127.0.0.1:8090/stat`;
- безопасные health и metrics API для внешнего мониторинга;
- маскирование RTMP URL в журналах.

## Состояние проекта

Это первая репозиторная версия существующего узла, а не готовый универсальный установщик. DVR отключён и вынесен в `legacy/`: его следующая реализация будет проектироваться заново.

В примерах используется имя `rtmp.cricket-stream.icu`. Оно задаётся конфигурацией и не является частью логики приложения. Перед развёртыванием обязательно проверьте доменные имена, пути сертификатов и замените все `CHANGE_ME_*`. Реальный `restream-config.json` нельзя добавлять в Git.

## Структура

- `app/` — Flask-менеджер и RTMP auth callback;
- `web/` — статическая страница мониторинга;
- `nginx/` — RTMP и HTTP/HLS конфигурация;
- `systemd/` — службы;
- `config/` — безопасный пример конфигурации;
- `docs/` — архитектура, безопасность и план развития;
- `legacy/` — отключённый исторический DVR только для справки.

## Каталог установки

Постоянные файлы узла размещаются в одном каталоге:

```text
/opt/cricket-rtmp-node/
├── app/       # Python-приложение
├── config/    # root-owned параметры запуска и примеры
├── logs/      # журналы исходящих ретрансляций
├── run/       # PID-файлы
├── state/     # изменяемая конфигурация потоков
├── web/       # статический интерфейс
└── .venv/     # Python environment
```

HLS-сегменты остаются в `/var/www/hls`: это временные медиаданные Nginx, а не файлы приложения. Конфигурации Nginx и systemd устанавливаются в стандартные системные каталоги из версий, хранящихся в репозитории.

## Быстрая проверка исходников

```bash
python3 -m py_compile app/restream_manager.py app/rtmp_auth.py
node --check web/script.js
python3 -m json.tool config/restream-config.example.json >/dev/null
python3 -m unittest discover -s tests -v
```

Развёртывание описано в [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Проверка будущего сервера без изменений:

```bash
sudo ./scripts/install.sh check
```

Первичная установка файлов выполняется отдельной явной командой. Она не активирует Nginx, systemd, DNS или TLS:

```bash
sudo ./scripts/install.sh install
```

Серверные Nginx-конфигурации создаются из отдельного профиля и только в staging-каталог:

```bash
cp config/nginx-render.example.json config/nginx-render.json
python3 scripts/render_nginx.py \
    --profile config/nginx-render.json \
    --output-dir build/nginx
```
