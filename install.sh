#!/bin/sh
# Install yeet into an isolated, user-owned uv tool environment.
set -eu

case "${1:-}" in
    -h|--help)
        printf '%s\n' 'Usage: sh install.sh [source]' \
            'Installs yeet from GitHub by default. Use . to install a local checkout.'
        exit 0
        ;;
esac
if [ "$#" -gt 1 ]; then
    printf '%s\n' 'Usage: sh install.sh [source]' >&2
    exit 1
fi

case "$(uname -s)" in
    Darwin|Linux) ;;
    *) printf '%s\n' 'Use the Windows installation instructions in README.md.' >&2; exit 1 ;;
esac

source_url=${1:-https://github.com/sohanmanju/yeet/archive/refs/heads/master.zip}
uv_command=$(command -v uv || true)
if [ -z "$uv_command" ]; then
    # Reuse a previous installation even when its directory is not on PATH yet.
    uv_install_dir=${UV_INSTALL_DIR:-"$HOME/.local/bin"}
    if [ -x "$uv_install_dir/uv" ]; then
        uv_command="$uv_install_dir/uv"
    else
        if ! command -v curl >/dev/null 2>&1; then
            printf '%s\n' 'curl is required. Install curl, then run this installer again.' >&2
            exit 1
        fi
        printf '%s\n' 'Installing uv…'
        installer=$(mktemp)
        trap 'rm -f "$installer"' EXIT
        trap 'exit 1' HUP INT TERM
        curl -fsSL https://astral.sh/uv/install.sh -o "$installer"
        UV_INSTALL_DIR="$uv_install_dir" UV_NO_MODIFY_PATH=1 sh "$installer"
        uv_command="$uv_install_dir/uv"
    fi
fi

printf '%s\n' 'Installing yeet (Python 3.12 will be downloaded if needed)…'
"$uv_command" tool install --python 3.12 --upgrade "$source_url"
"$uv_command" tool update-shell
bin_dir=$("$uv_command" tool dir --bin)
"$bin_dir/yeet" --version
printf '\n%s\n' 'Installed! Run: yeet' \
    'If your shell cannot find yeet, restart your terminal first.'
