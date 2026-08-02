#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEFAULT_TARGET="/opt/cricket-rtmp-node"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SOURCE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'EOF'
Usage:
  sudo ./scripts/install.sh check
  sudo ./scripts/install.sh install [options]

Options:
  --target PATH             Installation root (default: /opt/cricket-rtmp-node)
  --skip-python-deps        Create .venv but do not run pip install
  --skip-system-check       Skip checks for Nginx, RTMP module and FFmpeg
  --skip-service-user       Do not create/chown to cricket-rtmp (test packaging only)
  -h, --help                Show this help

The installer never modifies /etc/nginx, /etc/systemd/system, DNS or TLS.
It refuses to overwrite an existing target directory.
EOF
}

require_command() {
    local command_name="$1"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "MISSING: ${command_name}" >&2
        return 1
    fi
    echo "OK: ${command_name} -> $(command -v "$command_name")"
}

check_system() {
    local failed=0

    require_command python3 || failed=1
    require_command ffmpeg || failed=1
    require_command nginx || failed=1

    if command -v dpkg-query >/dev/null 2>&1; then
        if dpkg-query -W -f='${Status}\n' libnginx-mod-rtmp 2>/dev/null \
            | grep -qx 'install ok installed'; then
            echo "OK: libnginx-mod-rtmp installed"
        else
            echo "MISSING: libnginx-mod-rtmp" >&2
            failed=1
        fi
    else
        echo "WARNING: dpkg-query unavailable; RTMP module was not verified"
    fi

    if command -v python3 >/dev/null 2>&1; then
        python3 - <<'PY' || failed=1
import sys
print(f"Python: {sys.version.split()[0]}")
if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required")
PY
        python3 -m venv --help >/dev/null 2>&1 || {
            echo "MISSING: Python venv support" >&2
            failed=1
        }
    fi

    return "$failed"
}

copy_project() {
    local destination="$1"
    local item

    for item in \
        app config docs legacy nginx scripts systemd tests web \
        .gitignore README.md requirements.txt; do
        cp -a -- "${SOURCE_DIR}/${item}" "${destination}/"
    done
}

install_project() {
    local target="$1"
    local skip_python_deps="$2"
    local skip_system_check="$3"
    local skip_service_user="$4"
    local target_parent staging target_created=0

    if [[ "${EUID}" -ne 0 ]]; then
        echo "ERROR: install must run as root" >&2
        return 1
    fi

    if [[ "${target}" != /* || "${target}" == "/" ]]; then
        echo "ERROR: --target must be an absolute, non-root path" >&2
        return 1
    fi

    if [[ -e "${target}" ]]; then
        echo "ERROR: target already exists: ${target}" >&2
        echo "The initial installer does not overwrite existing installations." >&2
        return 1
    fi

    if [[ "${skip_system_check}" != "1" ]]; then
        check_system
    else
        require_command python3
    fi

    target_parent="$(dirname -- "${target}")"
    install -d -m 0755 -- "${target_parent}"
    staging="$(mktemp -d "${target_parent}/.cricket-rtmp-node.installing.XXXXXX")"

    cleanup() {
        if [[ -n "${staging:-}" && -d "${staging}" ]]; then
            find "${staging}" -depth -delete
        fi
        if [[ 
            "${target_created}" == "1"
            && -f "${target}/.cricket-rtmp-node-installing"
        ]]; then
            find "${target}" -depth -delete
        fi
    }
    trap cleanup EXIT

    copy_project "${staging}"

    install -d -m 0700 -- \
        "${staging}/config" \
        "${staging}/logs" \
        "${staging}/run" \
        "${staging}/state"

    install -m 0600 -- \
        "${staging}/config/node.env.example" \
        "${staging}/config/node.env"
    install -m 0600 -- \
        "${staging}/config/restream-config.example.json" \
        "${staging}/state/restream-config.json"

    touch "${staging}/.cricket-rtmp-node-installing"
    chmod 0644 "${staging}/.cricket-rtmp-node-installing"
    chmod 0755 "${staging}"
    mv -- "${staging}" "${target}"
    staging=""
    target_created=1

    # A virtual environment contains absolute shebang paths. It must be
    # created only after the project reaches its final installation path.
    python3 -m venv "${target}/.venv"
    if [[ "${skip_python_deps}" != "1" ]]; then
        "${target}/.venv/bin/pip" install \
            --disable-pip-version-check \
            -r "${target}/requirements.txt"
    fi

    if [[ "${skip_service_user}" != "1" ]]; then
        if ! getent group cricket-rtmp >/dev/null 2>&1; then
            groupadd --system cricket-rtmp
        fi
        if ! id -u cricket-rtmp >/dev/null 2>&1; then
            useradd \
                --system \
                --gid cricket-rtmp \
                --home-dir "${target}" \
                --no-create-home \
                --shell /usr/sbin/nologin \
                cricket-rtmp
        fi

        chown root:cricket-rtmp "${target}/config"
        chmod 0750 "${target}/config"
        chown root:cricket-rtmp "${target}/config/node.env"
        chmod 0640 "${target}/config/node.env"
        chown cricket-rtmp:cricket-rtmp \
            "${target}/state" \
            "${target}/state/restream-config.json" \
            "${target}/logs" \
            "${target}/run"
        chmod 0600 "${target}/state/restream-config.json"
        chmod 0700 "${target}/state" "${target}/logs" "${target}/run"
    fi

    unlink "${target}/.cricket-rtmp-node-installing"
    touch "${target}/.cricket-rtmp-node-managed"
    chmod 0644 "${target}/.cricket-rtmp-node-managed"
    trap - EXIT

    echo
    echo "Installed project files: ${target}"
    echo "Not activated: Nginx, systemd, DNS and TLS"
    echo
    echo "Next manual checks:"
    echo "  1. Edit ${target}/config/node.env"
    echo "  2. Replace every CHANGE_ME_* in ${target}/state/restream-config.json"
    echo "  3. Verify node.env is root:cricket-rtmp/640"
    echo "  4. Verify state/restream-config.json is cricket-rtmp:cricket-rtmp/600"
}

main() {
    local action="${1:-}"
    local target="${DEFAULT_TARGET}"
    local skip_python_deps=0
    local skip_system_check=0
    local skip_service_user=0

    if [[ -z "${action}" || "${action}" == "-h" || "${action}" == "--help" ]]; then
        usage
        return 0
    fi
    shift

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target)
                [[ $# -ge 2 ]] || {
                    echo "ERROR: --target requires a path" >&2
                    return 2
                }
                target="$2"
                shift 2
                ;;
            --skip-python-deps)
                skip_python_deps=1
                shift
                ;;
            --skip-system-check)
                skip_system_check=1
                shift
                ;;
            --skip-service-user)
                skip_service_user=1
                shift
                ;;
            -h|--help)
                usage
                return 0
                ;;
            *)
                echo "ERROR: unknown option: $1" >&2
                usage >&2
                return 2
                ;;
        esac
    done

    case "${action}" in
        check)
            check_system
            ;;
        install)
            install_project \
                "${target}" \
                "${skip_python_deps}" \
                "${skip_system_check}" \
                "${skip_service_user}"
            ;;
        *)
            echo "ERROR: expected 'check' or 'install'" >&2
            usage >&2
            return 2
            ;;
    esac
}

main "$@"
