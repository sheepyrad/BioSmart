#!/bin/sh
# Build the lockfile image, run it as this user, and open the localhost host.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

with_docker=0
for arg in "$@"; do
    case "$arg" in
        --with-docker) with_docker=1 ;;
        *)
            echo "usage: deploy/install.sh [--with-docker]" >&2
            exit 2
            ;;
    esac
done

if [ ! -f "$root/pixi.lock" ]; then
    echo "pixi.lock is missing. The image is built from the same lockfile as pixi install." >&2
    exit 1
fi

os_id=$(. /etc/os-release && printf '%s' "${ID:-}")

install_docker_ubuntu() {
    if [ "$os_id" != "ubuntu" ]; then
        echo "--with-docker installs Docker on Ubuntu. This host is ${os_id:-unknown}." >&2
        exit 1
    fi
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$(id -un)"
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
}

docker_info() {
    if docker info >/dev/null 2>&1; then
        docker info
        return 0
    fi
    if sudo -n docker info >/dev/null 2>&1; then
        sudo -n docker info
        return 0
    fi
    return 1
}

docker_cmd() {
    if docker info >/dev/null 2>&1; then
        docker "$@"
        return
    fi
    sudo -n docker "$@"
}

if ! docker_info >/dev/null 2>&1; then
    if [ "$with_docker" -eq 1 ]; then
        install_docker_ubuntu
    else
        echo "Docker is not available to this user." >&2
        echo "On Ubuntu, re-run: deploy/install.sh --with-docker" >&2
        echo "That installs Docker and the NVIDIA Container Toolkit with sudo." >&2
        exit 1
    fi
fi

if ! docker_info 2>/dev/null | grep -qi nvidia; then
    if [ "$with_docker" -eq 1 ]; then
        install_docker_ubuntu
    else
        echo "The NVIDIA Container Toolkit runtime is not configured for Docker." >&2
        echo "On Ubuntu, re-run: deploy/install.sh --with-docker" >&2
        exit 1
    fi
fi

home_mount=${BIOSMART_HOME_MOUNT:-"$HOME/.local/share/biosmart/home"}
runs_root=${BIOSMART_RUNS_ROOT:-"$HOME/BioSmart/runs"}
libraries_root=${BIOSMART_LIBRARIES_ROOT:-"$HOME/BioSmart/libraries"}
hf_cache=${BIOSMART_HF_CACHE:-${HF_HUB_CACHE:-"$HOME/.cache/huggingface/hub"}}
boltz_cache=${BIOSMART_BOLTZ_CACHE:-${BOLTZ_CACHE:-"$HOME/.boltz"}}
inputs=${BIOSMART_INPUTS:-"$HOME/BioSmart/inputs"}
tmp_dir=${BIOSMART_TMP:-"$HOME/BioSmart/tmp"}
pose_model=${BIOSMART_POSE_MODEL:-"$HOME/BioSmart/assets/cgflow_crossdock.ckpt"}
fabind_dir=${BIOSMART_FABIND_DIR:-"$HOME/BioSmart/assets/fabind"}
flashbind_dir=${BIOSMART_FLASHBIND_DIR:-"$HOME/BioSmart/assets/flashbind"}

mkdir -p \
    "$home_mount" \
    "$runs_root" \
    "$libraries_root" \
    "$hf_cache" \
    "$boltz_cache" \
    "$inputs" \
    "$tmp_dir" \
    "$(dirname "$pose_model")" \
    "$fabind_dir" \
    "$flashbind_dir" \
    "$HOME/.config/biosmart" \
    "$HOME/.local/share/applications" \
    "$HOME/.local/share/biosmart"

if [ -d "$pose_model" ]; then
    echo "Pose model path is a directory at $pose_model" >&2
    echo "Remove it, then run biosmart doctor fix weights." >&2
elif [ ! -f "$pose_model" ]; then
    echo "Pose model file is not at $pose_model" >&2
    echo "Set BIOSMART_POSE_MODEL, or run biosmart doctor fix weights after the host is up." >&2
fi

env_file="$HOME/.config/biosmart/compose.env"
umask 077
cat >"$env_file" <<EOF
BIOSMART_UID=$(id -u)
BIOSMART_GID=$(id -g)
BIOSMART_RUNS_ROOT=$runs_root
BIOSMART_LIBRARIES_ROOT=$libraries_root
BIOSMART_HF_CACHE=$hf_cache
BIOSMART_BOLTZ_CACHE=$boltz_cache
BIOSMART_INPUTS=$inputs
BIOSMART_HOME_MOUNT=$home_mount
BIOSMART_TMP=$tmp_dir
EOF
umask 022

# shellcheck disable=SC1091
. "$root/deploy/weight-mounts.sh"
weights_file="$HOME/.config/biosmart/weights.yaml"
mounts=$(weight_mount_lines "$pose_model" "$fabind_dir" "$flashbind_dir")
if [ -n "$mounts" ]; then
    umask 077
    {
        printf '%s\n' "services:" "  biosmart:" "    volumes:"
        printf '%s\n' "$mounts"
    } >"$weights_file"
    umask 022
fi

echo "Building biosmart:lock from $root/pixi.lock"
docker_cmd build -f deploy/Dockerfile -t biosmart:lock "$root"
if [ -n "$mounts" ]; then
    docker_cmd compose --env-file "$env_file" -f deploy/compose.yaml -f "$weights_file" up -d
else
    docker_cmd compose --env-file "$env_file" -f deploy/compose.yaml up -d
fi

install -m 0755 deploy/open-host.sh "$HOME/.local/share/biosmart/open-host.sh"
install -m 0644 deploy/biosmart.desktop "$HOME/.local/share/applications/biosmart.desktop"
if [ -d "$HOME/Desktop" ]; then
    install -m 0644 deploy/biosmart.desktop "$HOME/Desktop/BioSmart.desktop"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

"$HOME/.local/share/biosmart/open-host.sh"
