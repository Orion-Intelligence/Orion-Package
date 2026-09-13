#!/usr/bin/env bash
export SLUG=intelligence

push() {
    python3 -B "$REPO_PACKAGE_DIR/intelligence.py" build "$REPO_SOURCE_DIR" "$IMAGE" || return $?
    python3 -B "$PACKAGE_DIR/_shared/audit_image.py" "$IMAGE" "$SLUG" || return $?
    docker push "$IMAGE"
}

pull() {
    python3 -B "$REPO_PACKAGE_DIR/intelligence.py" pull "$ENV_FILE" "$IMAGE"
}
