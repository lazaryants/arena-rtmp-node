# Безопасность

- Реальный `state/restream-config.json` содержит publish keys и RTMP destinations; режим файла должен быть `600`.
- `config/node.env` принадлежит `root:arena-rtmp` и имеет режим `640`; рабочий JSON принадлежит сервисному пользователю и имеет режим `600`.
- Installer и updater нормализуют режимы кода и `.venv` независимо от umask вызывающей оболочки; root-owned код остаётся доступным сервисному пользователю только для чтения и выполнения.
- Изменения `state/restream-config.json` проходят строгую versioned schema-проверку и атомарную замену с `fsync`; невалидные данные не заменяют рабочий файл.
- Migration запускается только явно, предварительно создаёт backup с режимом `600` и не выводит конфигурационные значения.
- Updater требует явное подтверждение, блокирует параллельный запуск и сохраняет закрытый backup перед остановкой служб; ошибка после переключения вызывает rollback кода, state и units.
- RTMP URL и ключи нельзя добавлять в собственные сообщения журналов. API маскирует RTMP URL при выдаче диагностических строк, а файлы FFmpeg имеют режим `600`.
- Auth callback слушает только `127.0.0.1` и сравнивает ключи через `hmac.compare_digest`.
- XML RTMP stat слушает только `127.0.0.1`.
- Публичное API формируется по белому списку и не должно возвращать `key` или `restream_urls`.
- Административный UI и API защищаются на уровне Nginx.
- HLS сейчас публичен; это осознанная политика текущего узла, а не механизм контроля доступа.
- Node metrics содержат только агрегаты и безопасные состояния; добавлять туда URL, ключи, клиентские IP или строки журналов запрещено.
- Manager, supervisor и auth работают без root от отдельного пользователя `arena-rtmp` с systemd sandbox и пустым capability set.

При обнаружении уязвимости не публикуйте ключи, URL назначения или журналы в issue. Свяжитесь с владельцем репозитория приватно.


## MediaMTX compatibility boundary

The public MediaMTX process accepts only exact `place1/stream1` through
`place16/stream16` paths and delegates every RTMP publish decision to the
loopback Arena auth service. Existing per-place keys remain in the protected
Arena state file.

The compatibility forwarder uses a separate internal account:

- the main configuration stores its SHA-256 value;
- the ingress configuration stores the matching plaintext password;
- the account is restricted to localhost and canonical `place1` through
  `place16`;
- `/etc/mediamtx/ingress.yml` must be `root:mediamtx` with mode `640`;
- neither rendered MediaMTX file may be committed or printed.

MediaMTX API, HLS origin and metrics are bound to loopback. Nginx exposes only
the intended HLS routes. The normal updater installs unit definitions but never
copies private MediaMTX configuration and never restarts either MediaMTX
process.
