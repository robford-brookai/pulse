#!/usr/bin/env bash
# install-orca.sh — install the published Orca Linux build on the cloud host.
#
# Runs ON the host, driven from your Mac via:
#   aws ssm send-command --instance-ids "$ID" \
#     --document-name AWS-RunShellScript \
#     --parameters commands="$(cat scripts/orca-host/install-orca.sh)"
#
# Idempotent: re-running upgrades in place and re-verifies.

set -euo pipefail

# Keep this matched to the desktop client. A paired server running a different
# build is what the desktop's "Update Remote Orca Servers" panel is reporting.
ORCA_VERSION="${ORCA_VERSION:-1.4.182}"
ORCA_USER="${ORCA_USER:-ubuntu}"

log() { printf '==> %s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Resolve the architecture-matched package
# ---------------------------------------------------------------------------
case "$(dpkg --print-architecture)" in
  amd64) pkg_arch=amd64 ;;
  arm64) pkg_arch=arm64 ;;
  *) die "unsupported architecture: $(dpkg --print-architecture)" ;;
esac

deb="orca-ide_${ORCA_VERSION}_${pkg_arch}.deb"
url="https://github.com/stablyai/orca/releases/download/v${ORCA_VERSION}/${deb}"

log "installing $deb"

# ---------------------------------------------------------------------------
# 2. Install. apt resolves the Electron runtime dependencies from the .deb.
# ---------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates git

# The runtime shells out to `gh` for the Issues and PR work-items panel. It is
# not in Ubuntu's archive, so it needs GitHub's own repo — without it the panel
# fails whole with `spawn gh ENOENT` and reads as a dead connection rather than
# a missing tool. Install to /usr/bin, not ~/.local/bin: the runtime spawns gh
# directly, so it must resolve on the systemd unit's PATH.
keyring=/usr/share/keyrings/githubcli-archive-keyring.gpg
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | dd of="$keyring" status=none || die "could not fetch the GitHub CLI keyring"
chmod go+r "$keyring"
printf 'deb [arch=%s signed-by=%s] https://cli.github.com/packages stable main\n' \
  "$pkg_arch" "$keyring" > /etc/apt/sources.list.d/github-cli.list
apt-get update -qq
apt-get install -y -qq gh

# gh still needs credentials before the panel populates; an unauthenticated gh
# fails the same call with an auth error instead of ENOENT. Run once per host:
#   sudo -u "$ORCA_USER" gh auth login
command -v gh >/dev/null || die "gh not on PATH after install"

# The .deb under-declares its Electron runtime dependencies. Without these it
# installs cleanly and then dies at exec time on libgbm.so.1. Verified on
# Ubuntu 22.04.5 with orca-ide 1.4.180.
apt-get install -y -qq \
  libgbm1 libasound2 libnss3 libxss1 libxtst6 libgtk-3-0 libdrm2 libxshmfence1

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/$deb" "$url" || die "download failed: $url"
apt-get install -y -qq "$tmp/$deb"

# ---------------------------------------------------------------------------
# 3. Verify. On Linux the binary is orca-ide — bare `orca` is the GNOME screen
#    reader, and running it would start speech synthesis rather than a runtime.
# ---------------------------------------------------------------------------
command -v orca-ide >/dev/null || die "orca-ide not on PATH after install"

if ! sudo -u "$ORCA_USER" orca-ide serve --help >/dev/null 2>&1; then
  die "orca-ide is installed but 'serve' did not run. Capture the error with:
       sudo -u $ORCA_USER orca-ide serve --help
     If it fails on a missing display, the headless build needs xvfb:
       apt-get install -y xvfb  # then wrap ExecStart in xvfb-run -a"
fi

log "orca-ide ${ORCA_VERSION} installed and 'serve' verified"
