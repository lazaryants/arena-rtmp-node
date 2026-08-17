# Первая миграция исторического узла

Этот документ описывает переход с разрозненных файлов в `/opt`, `/var/www/html` и `/var/log` на управляемую установку `/opt/arena-rtmp-node`. Он не является командой немедленно менять production.

## Неизменяемые условия

- До согласованного окна действующий домен, Nginx и сертификат остаются прежними.
- RTMP applications `place1`–`place16`, stream keys и HLS URL сохраняются.
- Реальный server profile и рабочий `restream-config.json` не добавляются в Git.
- DVR можно остановить и удалить отдельно: его исторические данные не переносятся.
- Сначала разворачивается параллельный staging-каталог; существующие `/opt/restream_manager.py`, `/opt/rtmp_auth.py` и службы не заменяются.

## Фаза 1. Read-only инвентаризация

Перед любыми изменениями сохранить вывод без значений ключей и destination URL:

```bash
systemctl is-active nginx rtmp-auth restream-manager dvr-recorder
systemctl cat rtmp-auth restream-manager dvr-recorder
nginx -T 2>/dev/null > /root/nginx-before-arena-rtmp-node.txt
ss -ltnp
find /opt /etc/systemd/system /etc/nginx \
    -maxdepth 3 -type f \
    -printf '%M %u:%g %s %p\n' \
    | sort
```

Содержимое рабочего JSON и журналов в терминал не выводить.

## Фаза 2. Параллельная установка без активации

Из отдельного проверенного release checkout:

```bash
sudo ./scripts/install.sh check
sudo ./scripts/install.sh install
```

Installer создаёт `/opt/arena-rtmp-node`, но не меняет Nginx, systemd, DNS или TLS. После этого рабочий JSON копируется локально с сохранением режима `600` и проходит read-only migration check. Применение migration выполняется только после отдельного backup.

## Фаза 3. Private server profile

На сервере создаётся игнорируемый Git файл `config/nginx-render.json`. Пока новый сертификат не выпущен, в нём временно указывается действующее имя и его TLS paths. Это значение не переносится в исходный код. После выпуска сертификата профиль и `ARENA_RTMP_PUBLIC_HOST` переключаются на `rtmp.arena76.top` одним согласованным изменением.

Renderer пишет только в staging:

```bash
python3 scripts/render_nginx.py \
    --profile config/nginx-render.json \
    --output-dir build/nginx
```

Сгенерированные файлы сравниваются с `nginx -T`; до `nginx -t` и явного подтверждения они не устанавливаются.

## Фаза 4. Sandbox и функциональная проверка

Офлайн-порог repository units:

```bash
python3 scripts/audit_systemd.py --max-exposure 3.0
```

После временной установки units на staging-сервере повторить аудит по именам активных служб и проверить:

- manager health и metrics не раскрывают URL/ключи;
- неправильный publish key отклоняется, правильный принимается;
- manager restart не останавливает исходящий FFmpeg;
- supervisor restart корректно завершает принадлежащие ему FFmpeg;
- HLS `place1`, `place3`, `place8`, `place16` продолжает обновляться;
- rollback updater возвращает прежнюю версию.

## Фаза 5. Production cutover

Cutover выполняется только после отдельного плана с точными backup paths и rollback-командами. Nginx остаётся последним переключаемым компонентом. Сначала запускаются supervisor, auth и manager из нового каталога; затем проверяются локальные endpoints; только после этого применяется заранее проверенный Nginx diff.

Старые файлы и units не удаляются в день cutover. Они переводятся в отключённое состояние и сохраняются до завершения контрольного периода.
