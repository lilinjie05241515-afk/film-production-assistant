#!/bin/sh
# Usage: sh release/bootstrap.sh [--python /absolute/python3] ACTION [ARGUMENTS...]
# This wrapper only selects an existing interpreter; it never downloads software.
set -eu

film_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
film_installer="$film_script_dir/installer.py"
if [ ! -f "$film_installer" ]; then
    printf '%s\n' '找不到同目录 installer.py；请完整解压发行包。' >&2
    exit 2
fi

film_override=''
if [ "${1-}" = '--python' ]; then
    if [ "$#" -lt 3 ]; then
        printf '%s\n' '用法：sh release/bootstrap.sh [--python /绝对路径/python3] 操作 [安装器参数...]' >&2
        exit 2
    fi
    film_override=$2
    shift 2
fi
if [ "$#" -eq 0 ]; then
    printf '%s\n' '用法：sh release/bootstrap.sh [--python /绝对路径/python3] 操作 [安装器参数...]' >&2
    exit 2
fi
film_action=$1
shift
case "$film_action" in
    env|verify|install|stage|status|check-update|switch|rollback|recover|host-plan|deactivate|uninstall|duplicates|migrate-entry|restore-entry) ;;
    *) printf '%s\n' "未知安装器操作：$film_action" >&2; exit 2 ;;
esac
for film_argument in "$@"; do
    case "$film_argument" in
        --python|--python=*)
            printf '%s\n' '使用 bootstrap.sh 时，请把 --python /绝对路径 放在操作名称之前。' >&2
            exit 2
            ;;
    esac
done

film_probe_python() {
    "$1" -I -c 'import os,sys,sqlite3; sys.exit(2) if sys.version_info < (3,11) else None; print(os.path.realpath(sys.executable))' 2>/dev/null
}

film_python=''
if [ -n "$film_override" ]; then
    case "$film_override" in
        /*) ;;
        *) printf '%s\n' '--python 必须指定解释器的绝对路径。' >&2; exit 2 ;;
    esac
    if film_python=$(film_probe_python "$film_override"); then :; else
        printf '%s\n' '指定的 Python 不可运行或不满足 Python 3.11+（含 sqlite3）。不会改用其他解释器或自动下载。' >&2
        exit 2
    fi
else
    if film_path_python=$(command -v python3 2>/dev/null); then
        if film_python=$(film_probe_python "$film_path_python"); then :; else film_python=''; fi
    fi
    if [ -z "$film_python" ]; then
        for film_candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
            if [ -x "$film_candidate" ]; then
                if film_python=$(film_probe_python "$film_candidate"); then break; else film_python=''; fi
            fi
        done
    fi
fi
if [ -z "$film_python" ]; then
    printf '%s\n' '需要 Python 3.11 或更新版本（含 sqlite3）。安装后重试，或在操作前用 --python 指定绝对路径。安装器不会自动下载。' >&2
    exit 2
fi

# Every argument remains one argument, including spaces, Chinese and shell metacharacters.
case "$film_action" in
    env|install|stage)
        exec "$film_python" -B -X utf8 "$film_installer" "$film_action" "$@" --python "$film_python"
        ;;
    *) exec "$film_python" -B -X utf8 "$film_installer" "$film_action" "$@" ;;
esac
