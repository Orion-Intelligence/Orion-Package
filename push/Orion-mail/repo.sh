#!/usr/bin/env bash
export SLUG=mail

push() {
    python3 -B "$REPO_PACKAGE_DIR/mail.py" build "$REPO_SOURCE_DIR" "$IMAGE" || return $?
    docker push "$IMAGE"
}

pull() {
    python3 -B "$REPO_PACKAGE_DIR/mail.py" pull "$ENV_FILE" "$IMAGE"
}
