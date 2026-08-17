# Nginx configuration

Файлы в `templates/` универсальны и не являются готовой конфигурацией конкретного сервера. Их рендерит `scripts/render_nginx.py` из закрытого server profile.

Результат состоит из трёх файлов:

- `arena-rtmp.conf` — корневой RTMP context;
- `arena-rtmp-http.conf` — HTTPS, UI, API proxy и HLS;
- `arena-rtmp-stat-local.conf` — локальная RTMP-статистика.

`arena-rtmp.conf` нельзя помещать в стандартный `/etc/nginx/conf.d`, потому что на Ubuntu этот каталог подключается внутри `http {}`. Для него нужен root-level include, например:

```nginx
include /etc/nginx/rtmp-enabled/*.conf;
```

Остальные два файла можно устанавливать в `/etc/nginx/conf.d/`. Renderer ничего туда не копирует и Nginx не перезагружает.
