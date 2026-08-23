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

## MediaMTX HLS paths

A render profile can route selected public HLS paths through a local MediaMTX
instance while all other places continue to use Nginx-RTMP files:

```json
"mediamtx_hls_upstream": "127.0.0.1:8888",
"mediamtx_hls_places": [9, 10]
```

For every selected place, the renderer creates a prefix location before the
generic file-backed HLS location. The existing public master name
`/hls/placeN/streamN.m3u8` is translated to MediaMTX
`/placeN/index.m3u8`; child playlists, initialization files and fMP4 segments
remain under the same public prefix. The upstream is restricted to loopback.
