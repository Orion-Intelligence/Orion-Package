#!/usr/bin/env bash
export SLUG=intelligence

push() {
    python3 -B "$REPO_PACKAGE_DIR/intelligence.py" build "$REPO_SOURCE_DIR" "$IMAGE" || return $?
    docker push "$IMAGE"
}

pull() {
    python3 -B "$REPO_PACKAGE_DIR/intelligence.py" pull "$ENV_FILE" "$IMAGE"
}
