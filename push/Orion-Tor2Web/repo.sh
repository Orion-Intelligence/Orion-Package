export SLUG=tor2web

push() {
    docker build --build-context "orion_obfuscation=$PACKAGE_DIR/_shared/obfuscation" --file "$REPO_PACKAGE_DIR/Dockerfile" --tag "$IMAGE" "$REPO_SOURCE_DIR" || return $?
    python3 -B "$PACKAGE_DIR/_shared/audit_image.py" "$IMAGE" "$SLUG" || return $?
    docker push "$IMAGE" || return $?
}

pull() {
    export ORION_PACKAGE_IMAGE="$IMAGE"
    printf 'Keep your existing certificate renewal job enabled; nginx reloads certificates every 12 hours.\n'
    docker pull "$IMAGE" || return $?
    python3 -B "$PACKAGE_DIR/pull/_shared/deployment.py" --apply Orion-Tor2Web || return $?
    python3 -B "$(dirname -- "$ENV_FILE")/fill_env.py" || return $?
    python3 -B "$(dirname -- "$ENV_FILE")/setup.py" || return $?
    compose run --rm --no-deps tor2web --check || return $?
    compose up --detach --wait --wait-timeout 300 || return $?
}

compose() {
    local args=(--project-name orion-package --file "$REPO_PACKAGE_DIR/compose.yml")
    [[ ! -f "$ENV_FILE" ]] || args+=(--env-file "$ENV_FILE")
    docker compose "${args[@]}" "$@"
}
