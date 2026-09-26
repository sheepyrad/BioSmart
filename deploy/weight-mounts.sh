# Volume lines for weights the Doctor may write.
# A missing Pose model file is not a mount source. Docker would create a
# directory at that path and hide the Pose model destination.

weight_mount_lines() {
    pose_model=$1
    fabind_dir=$2
    flashbind_dir=$3
    if [ -f "$pose_model" ]; then
        printf '      - %s:%s\n' \
            "$pose_model" \
            "/opt/biosmart/cgflow/weights/cgflow_crossdock.ckpt"
    elif [ ! -e "$pose_model" ] && [ -d "$(dirname "$pose_model")" ]; then
        printf '      - %s:%s\n' \
            "$(dirname "$pose_model")" \
            "/opt/biosmart/cgflow/weights"
    fi
    if [ -d "$fabind_dir" ]; then
        printf '      - %s:%s\n' \
            "$fabind_dir" \
            "/opt/biosmart/cgflow/src/FlashBind/FABind_plus/ckpt"
    fi
    if [ -d "$flashbind_dir" ]; then
        printf '      - %s:%s\n' \
            "$flashbind_dir" \
            "/opt/biosmart/cgflow/src/FlashBind/checkpoints"
    fi
}
