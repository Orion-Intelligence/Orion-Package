# Orion Package

[Documentation](https://orion-search.readthedocs.io) · [Service Status](https://uptime.orionintelligence.org/status/orion-intelligence) · [Orion Platform](https://github.com/Orion-Intelligence/Orion-Intelligence)

Standalone Docker packaging for the Orion platform. `push.sh` builds and publishes images;
`pull.sh` downloads images, prepares runtime services and starts the selected deployments.

## Quick Start

### Prerequisites

- Bash, Python 3.12+ and Docker Engine with Docker Compose v2.
- Docker Hub write access to `msmannan00` for publishing.
- For builds, place the application repositories beside this repository:

```text
Orion/
├── Orion-Package/
├── Orion-Tor2Web/
├── Orion-Micros/
├── Orion-Social/
├── Orion-Dark-Nexus/
└── Orion-mail/
```

Set `ORION_BASE_DIR` if your application repositories live elsewhere. Scripts work from any working directory.

### Configure and pull

For each selected service, copy its template and edit the local `.env`:

```bash
cd Orion-Package
cp Orion-mail/template-env Orion-mail/.env
chmod 600 Orion-mail/.env
# Edit Orion-mail/.env before pulling.
./pull.sh
```

Each template separates static service settings from deployment values. Keep internal Docker names, network
addresses, fixed service URLs and ports consistent with the existing Orion deployment. Replace every `{value}`
with the appropriate credential or deployment setting. An explicitly unused optional integration may use an
empty value, if the application supports it. Never use `{value}` as a real password.

Pull checks all selected environment files before making any Docker calls. Missing `.env` files and unresolved
placeholders stop deployment. Templates are intended for Git; populated `.env` files, runtime files and private
keys are ignored. Secrets are not included in image build contexts.

Use existing credentials when reusing databases or encrypted storage; generating replacement keys does not migrate
existing data. Public Mail URLs must use HTTPS. Production Compose overrides development-only internal SMTP and
cookie settings; do not replace its internal Docker service names with public hostnames.

### Build and push

```bash
./push.sh
```

Enter a Docker Hub token with write access when prompted. Push only builds and publishes; it does not deploy,
provision certificates or require a configured runtime `.env`. Each supported repository publishes one application
image under `msmannan00/orion-<service>:latest`; deployments may also run supporting database/proxy images.

Both menus use Up/Down to move, Space to toggle, Enter to run and q/Esc to cancel. All selects or clears every
repository; selecting every individual entry checks All, and deselecting one clears it.

`ORION_IMAGE_NAMESPACE` and `ORION_IMAGE_TAG` override the registry namespace and image tag.

## Supported Services

Tor2Web, Micros, Social, Dark Nexus and Mail have build/pull handlers. Crawler, Intelligence, Sandbox and Storage
remain visible in the menu but are not implemented.

Each repository folder owns its Docker/runtime configuration and environment template. `_shared/` contains only
the common selection, backend packaging and configuration-checking code.

Pull uses image contents rather than source-code bind mounts, but does not provision a clean host automatically.
Existing persistent data paths default to the sibling application directories. `ORION_RUNTIME_DIR` can relocate
Micros/Social runtime data; `ORION_MAIL_ATTACHMENTS` can relocate Mail attachments. Keep existing volume names,
network configuration and credentials when upgrading an earlier `run.sh` deployment.

- Tor2Web needs its matching Let's Encrypt certificate and an enabled external renewal job.
- Mail needs the existing shared HTTPS edge proxy, its mail route, a matching certificate, DNS and renewal setup.
  It preserves mail data and prepares Rspamd/DKIM runtime configuration during pull; publish the generated public
  DKIM record in DNS when needed. Never publish private keys.
- Dark Nexus needs its existing sandbox egress firewall and the configured sandbox image on the deployment host.

## Publishing This Repository

Review `git status` and the files being committed before pushing. Commit `template-env`, never a populated `.env`.
Use your chosen Git remote; this repository's scripts publish Docker images, not Git commits.
