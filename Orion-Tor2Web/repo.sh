export SLUG=tor2web

push() {
    docker build --file "$REPO_PACKAGE_DIR/Dockerfile" --tag "$IMAGE" "$REPO_SOURCE_DIR" || return $?
    docker push "$IMAGE" || return $?
}

pull() {
    export ORION_PACKAGE_IMAGE="$IMAGE"
    printf 'Keep your existing certificate renewal job enabled; nginx reloads certificates every 12 hours.\n'
    compose pull || return $?
    compose run --rm --no-deps tor2web --check || return $?
    compose up --detach --wait --wait-timeout 300 || return $?
}

compose() {
    local args=(--project-name orion-package --file "$REPO_PACKAGE_DIR/compose.yml")
    [[ ! -f "$ENV_FILE" ]] || args+=(--env-file "$ENV_FILE")
    docker compose "${args[@]}" "$@"
}
