#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEFAULT_TARGET="/opt/arena-rtmp-node"
readonly DEFAULT_BACKUP_ROOT="/var/backups/arena-rtmp-node"
readonly DEFAULT_SYSTEMD_DIR="/etc/systemd/system"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SOURCE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly SERVICES=(
    arena-restream-supervisor.service
    arena-rtmp-auth.service
    arena-restream-manager.service
)
readonly MANAGED_DIRECTORIES=(
    app docs legacy logrotate nginx scripts systemd tests web
)
readonly MANAGED_FILES=(
    .gitignore README.md requirements.txt
)

TARGET="${DEFAULT_TARGET}"
BACKUP_ROOT="${DEFAULT_BACKUP_ROOT}"
SYSTEMD_DIR="${DEFAULT_SYSTEMD_DIR}"
ACTION=""
CONFIRM=""
SKIP_SERVICES=0
SKIP_HEALTH_CHECK=0
SKIP_OWNERSHIP=0
BACKUP_DIR=""
ROLLBACK_REQUIRED=0
SERVICES_STOPPED=0
declare -a PREVIOUSLY_ACTIVE=()

usage() {
    cat <<'EOF'
Usage:
  sudo ./scripts/update.sh check [options]
  sudo ./scripts/update.sh apply --confirm UPDATE [options]

Options:
  --target PATH          Managed installation (default: /opt/arena-rtmp-node)
  --backup-root PATH     Backup parent (default: /var/backups/arena-rtmp-node)
  --systemd-dir PATH     Unit destination (default: /etc/systemd/system)
  --skip-services        Do not install/restart units (test packaging only)
  --skip-ownership       Do not enforce root ownership (test packaging only)
  --skip-health-check    Skip manager HTTP readiness check
  --confirm UPDATE       Required literal confirmation for apply
  -h, --help             Show this help

The updater does not modify Nginx, DNS, TLS, HLS media, logs or runtime PID files.
It does not update Python dependencies; requirements must already be satisfied.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    return 1
}

require_absolute_safe_path() {
    local label="$1"
    local path="$2"
    [[ "${path}" == /* && "${path}" != "/" ]] \
        || fail "${label} must be an absolute, non-root path"
}

validate_source() {
    python3 -m py_compile \
        "${SOURCE_DIR}"/app/*.py \
        "${SOURCE_DIR}"/scripts/*.py
    python3 -m json.tool \
        "${SOURCE_DIR}/config/restream-config.example.json" \
        >/dev/null
    bash -n "${SOURCE_DIR}/scripts/install.sh"
    bash -n "${SOURCE_DIR}/scripts/update.sh"
}

validate_target() {
    require_absolute_safe_path "target" "${TARGET}"
    require_absolute_safe_path "backup root" "${BACKUP_ROOT}"
    require_absolute_safe_path "systemd directory" "${SYSTEMD_DIR}"
    [[ -d "${TARGET}" ]] || fail "target does not exist: ${TARGET}"
    [[ -f "${TARGET}/.arena-rtmp-node-managed" ]] \
        || fail "target is not marked as a managed installation"
    [[ -x "${TARGET}/.venv/bin/python" ]] \
        || fail "target Python environment is missing"
    [[ -f "${TARGET}/state/restream-config.json" ]] \
        || fail "working configuration is missing"
    [[ "${SOURCE_DIR}" != "${TARGET}" ]] \
        || fail "run update.sh from a separate release checkout"
    if [[ "${SKIP_SERVICES}" != "1" \
        && "${TARGET}" != "${DEFAULT_TARGET}" \
        && "${SKIP_OWNERSHIP}" != "1" ]]; then
        fail "packaged systemd units require target ${DEFAULT_TARGET}"
    fi
}

check_python_dependencies() {
    "${TARGET}/.venv/bin/python" - <<'PY'
import flask
import gunicorn
import psutil
print("Installed Python dependencies are importable.")
PY
    "${TARGET}/.venv/bin/pip" check
    "${TARGET}/.venv/bin/pip" install \
        --disable-pip-version-check \
        --dry-run \
        --no-index \
        --requirement "${SOURCE_DIR}/requirements.txt" \
        >/dev/null
}

check_migration() {
    local status=0
    "${TARGET}/.venv/bin/python" \
        "${SOURCE_DIR}/scripts/migrate_config.py" \
        --config "${TARGET}/state/restream-config.json" \
        || status=$?
    [[ "${status}" == "0" || "${status}" == "2" ]] \
        || fail "configuration cannot be migrated safely"
}

preflight() {
    command -v python3 >/dev/null || fail "python3 is required"
    command -v flock >/dev/null || fail "flock is required"
    if [[ "${SKIP_SERVICES}" != "1" ]]; then
        command -v systemctl >/dev/null || fail "systemctl is required"
        command -v curl >/dev/null || fail "curl is required"
    fi
    validate_source
    validate_target
    check_python_dependencies
    check_migration
    echo "Preflight checks passed. No files changed."
}

remember_services() {
    local service
    PREVIOUSLY_ACTIVE=()
    for service in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "${service}"; then
            PREVIOUSLY_ACTIVE+=("${service}")
        fi
    done
}

stop_services() {
    local service
    for service in arena-restream-manager.service arena-rtmp-auth.service \
        arena-restream-supervisor.service; do
        systemctl stop "${service}" 2>/dev/null || true
    done
    SERVICES_STOPPED=1
}

start_previous_services() {
    local service
    for service in arena-restream-supervisor.service arena-rtmp-auth.service \
        arena-restream-manager.service; do
        if [[ " ${PREVIOUSLY_ACTIVE[*]} " == *" ${service} "* ]]; then
            systemctl start "${service}"
        fi
    done
    SERVICES_STOPPED=0
}

create_backup() {
    local stamp item unit
    stamp="$(date -u +%Y%m%d-%H%M%S)"
    install -d -m 0700 -- "${BACKUP_ROOT}"
    BACKUP_DIR="$(mktemp -d "${BACKUP_ROOT}/update-${stamp}.XXXXXX")"
    chmod 0700 "${BACKUP_DIR}"
    install -d -m 0700 -- "${BACKUP_DIR}/target" "${BACKUP_DIR}/systemd"

    for item in "${MANAGED_DIRECTORIES[@]}" "${MANAGED_FILES[@]}"; do
        if [[ -e "${TARGET}/${item}" ]]; then
            cp -a --parents -- "${TARGET}/${item}" "${BACKUP_DIR}/target"
        fi
    done
    cp -a --parents -- \
        "${TARGET}/config" \
        "${TARGET}/state" \
        "${TARGET}/.arena-rtmp-node-managed" \
        "${BACKUP_DIR}/target"

    if [[ "${SKIP_SERVICES}" != "1" ]]; then
        for unit in "${SERVICES[@]}"; do
            if [[ -e "${SYSTEMD_DIR}/${unit}" ]]; then
                cp -a -- "${SYSTEMD_DIR}/${unit}" "${BACKUP_DIR}/systemd/"
            fi
        done
    fi
    printf '%s\n' "${PREVIOUSLY_ACTIVE[@]}" \
        >"${BACKUP_DIR}/previously-active-services.txt"
    chmod -R go-rwx "${BACKUP_DIR}"
    echo "Protected backup created: ${BACKUP_DIR}"
}

replace_managed_files() {
    local item
    for item in "${MANAGED_DIRECTORIES[@]}"; do
        if [[ -e "${TARGET}/${item}" ]]; then
            find "${TARGET}/${item}" -depth -delete
        fi
        cp -a -- "${SOURCE_DIR}/${item}" "${TARGET}/${item}"
    done
    find "${TARGET}" -type f -name '*.py[co]' -delete
    find "${TARGET}" -type d -name __pycache__ -empty -delete
    for item in "${MANAGED_FILES[@]}"; do
        install -m 0644 -- "${SOURCE_DIR}/${item}" "${TARGET}/${item}"
    done

    # Update repository-owned examples while preserving node.env and the
    # private Nginx render profile from the installation.
    install -m 0644 -- \
        "${SOURCE_DIR}/config/gunicorn.conf.py" \
        "${SOURCE_DIR}/config/node.env.example" \
        "${SOURCE_DIR}/config/nginx-render.example.json" \
        "${SOURCE_DIR}/config/restream-config.example.json" \
        "${TARGET}/config/"
    for item in "${MANAGED_DIRECTORIES[@]}"; do
        find "${TARGET}/${item}" -type d -exec chmod 0755 {} +
        find "${TARGET}/${item}" -type f -exec chmod 0644 {} +
    done
    find "${TARGET}/scripts" \
        -maxdepth 1 \
        -type f \
        ! -name '__init__.py' \
        -exec chmod 0755 {} +
    if [[ "${SKIP_OWNERSHIP}" != "1" ]]; then
        chown -R root:root \
            "${TARGET}/app" \
            "${TARGET}/docs" \
            "${TARGET}/legacy" \
            "${TARGET}/logrotate" \
            "${TARGET}/nginx" \
            "${TARGET}/scripts" \
            "${TARGET}/systemd" \
            "${TARGET}/tests" \
            "${TARGET}/web"
    fi
}

install_units() {
    local unit
    for unit in "${SERVICES[@]}"; do
        install -m 0644 -- \
            "${TARGET}/systemd/${unit}" \
            "${SYSTEMD_DIR}/${unit}"
    done
    systemctl daemon-reload
}

validate_installed_release() {
    "${TARGET}/.venv/bin/python" -m py_compile "${TARGET}"/app/*.py
    PYTHONPATH="${TARGET}" "${TARGET}/.venv/bin/python" - <<PY
from app.config_store import ConfigStore
config = ConfigStore("${TARGET}/state/restream-config.json").load()
assert config["schema_version"] >= 1
PY
}

wait_for_manager() {
    local attempt
    for attempt in {1..20}; do
        if curl --fail --silent --show-error \
            --max-time 2 \
            http://127.0.0.1:5000/api/node/health \
            >/dev/null; then
            return 0
        fi
        sleep 1
    done
    fail "manager health endpoint did not become ready"
}

restore_backup() {
    local item unit backup_target
    [[ -n "${BACKUP_DIR}" && -d "${BACKUP_DIR}" ]] || return 0
    backup_target="${BACKUP_DIR}/target${TARGET}"

    for item in "${MANAGED_DIRECTORIES[@]}" "${MANAGED_FILES[@]}" config state; do
        if [[ -e "${TARGET}/${item}" ]]; then
            find "${TARGET}/${item}" -depth -delete
        fi
        if [[ -e "${backup_target}/${item}" ]]; then
            cp -a -- "${backup_target}/${item}" "${TARGET}/${item}"
        fi
    done
    cp -a -- \
        "${backup_target}/.arena-rtmp-node-managed" \
        "${TARGET}/.arena-rtmp-node-managed"

    if [[ "${SKIP_SERVICES}" != "1" ]]; then
        for unit in "${SERVICES[@]}"; do
            if [[ -e "${BACKUP_DIR}/systemd/${unit}" ]]; then
                install -m 0644 -- \
                    "${BACKUP_DIR}/systemd/${unit}" \
                    "${SYSTEMD_DIR}/${unit}"
            else
                if [[ -e "${SYSTEMD_DIR}/${unit}" ]]; then
                    unlink "${SYSTEMD_DIR}/${unit}"
                fi
            fi
        done
        systemctl daemon-reload
    fi
}

rollback_on_error() {
    local exit_code=$?
    trap - ERR
    if [[ "${ROLLBACK_REQUIRED}" == "1" ]]; then
        echo "Update failed; restoring ${BACKUP_DIR}" >&2
        if [[ "${SKIP_SERVICES}" != "1" ]]; then
            stop_services
        fi
        restore_backup
        if [[ "${SKIP_SERVICES}" != "1" ]]; then
            start_previous_services || true
        fi
        echo "Rollback completed." >&2
    fi
    exit "${exit_code}"
}

apply_update() {
    [[ "${EUID}" == "0" || "${SKIP_OWNERSHIP}" == "1" ]] \
        || fail "apply must run as root"
    [[ "${CONFIRM}" == "UPDATE" ]] \
        || fail "apply requires the literal option: --confirm UPDATE"

    preflight
    install -d -m 0700 -- "${BACKUP_ROOT}"
    exec 9>"${BACKUP_ROOT}/.update.lock"
    flock -n 9 || fail "another update is already running"

    if [[ "${SKIP_SERVICES}" != "1" ]]; then
        remember_services
    fi
    create_backup
    ROLLBACK_REQUIRED=1
    trap rollback_on_error ERR

    if [[ "${SKIP_SERVICES}" != "1" ]]; then
        stop_services
    fi

    "${TARGET}/.venv/bin/python" \
        "${SOURCE_DIR}/scripts/migrate_config.py" \
        --config "${TARGET}/state/restream-config.json" \
        --apply
    replace_managed_files
    validate_installed_release

    if [[ "${SKIP_SERVICES}" != "1" ]]; then
        install_units
        start_previous_services
        if [[ "${SKIP_HEALTH_CHECK}" != "1" \
            && " ${PREVIOUSLY_ACTIVE[*]} " == *" arena-restream-manager.service "* ]]; then
            wait_for_manager
        fi
    fi

    trap - ERR
    ROLLBACK_REQUIRED=0
    echo "Update completed successfully. Backup retained: ${BACKUP_DIR}"
}

parse_arguments() {
    ACTION="${1:-}"
    [[ -n "${ACTION}" ]] || { usage; return 2; }
    if [[ "${ACTION}" == "-h" || "${ACTION}" == "--help" ]]; then
        usage
        exit 0
    fi
    shift
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target) TARGET="${2:?missing --target value}"; shift 2 ;;
            --backup-root) BACKUP_ROOT="${2:?missing --backup-root value}"; shift 2 ;;
            --systemd-dir) SYSTEMD_DIR="${2:?missing --systemd-dir value}"; shift 2 ;;
            --confirm) CONFIRM="${2:?missing --confirm value}"; shift 2 ;;
            --skip-services) SKIP_SERVICES=1; shift ;;
            --skip-ownership) SKIP_OWNERSHIP=1; shift ;;
            --skip-health-check) SKIP_HEALTH_CHECK=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) fail "unknown option: $1"; usage >&2; return 2 ;;
        esac
    done
}

main() {
    parse_arguments "$@"
    case "${ACTION}" in
        check) preflight ;;
        apply) apply_update ;;
        *) fail "expected check or apply"; usage >&2; return 2 ;;
    esac
}

main "$@"
