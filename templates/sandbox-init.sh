#!/bin/bash
# sandbox-code per-project init script (OPT-IN TEMPLATE — copy, don't run as-is).
#
# The base image ships WITHOUT language runtimes. To give a project Go, Java,
# Maven, Clojure (or anything else), copy this file into the project's
# .sandbox-code/ folder as .sandbox-code/sandbox-init.sh and trim it to only
# what the project needs.
#
# - Runs as root, once per project (content hash is cached in the persistent
#   opencode-data volume — see --no-init / --force-init / --init-script).
# - Projects WITHOUT a sandbox-init.sh get nothing extra: no installs happen.
#
# Example: a pure-TypeScript project should replace this file with an empty
# one (or none), while a Go project keeps just the Go section.

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update

# --- Go ----------------------------------------------------------------------
if ! command -v go >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends golang
fi

# --- Java (Temurin JDK) + Maven ----------------------------------------------
if ! command -v java >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends ca-certificates gnupg lsb-release
    wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public \
        | gpg --dearmor -o /usr/share/keyrings/adoptium-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/adoptium-archive-keyring.gpg] https://packages.adoptium.net/artifactory/deb $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/adoptium.list
    apt-get update
    apt-get install -y --no-install-recommends temurin-26-jdk maven
fi

# --- Clojure -----------------------------------------------------------------
if ! command -v clojure >/dev/null 2>&1; then
    cd /tmp
    curl -L -O https://github.com/clojure/brew-install/releases/latest/download/linux-install.sh
    chmod +x linux-install.sh
    ./linux-install.sh
    rm -f linux-install.sh
fi

# --- Chromium (headless) ------------------------------------------------------
# NOTE: on Ubuntu, `chromium-browser` is a snap wrapper. Without a working
# snapd inside the container it installs but will not run. If that's the case,
# prefer project tooling instead: `npx playwright install --with-deps chromium`.
if ! command -v chromium-browser >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends chromium-browser
fi

# --- Utils (extracted from the base image to keep it lean) -------------------

# PDF utilities (pdftotext, pdfinfo, pdfimages, ...)
if ! command -v pdftotext >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends poppler-utils
fi

# Network diagnostics (gping, dig/nslookup, ip, ping)
if ! command -v gping >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends gping bind9-dnsutils iproute2 iputils-ping
fi

apt-get clean
rm -rf /var/lib/apt/lists/*

# Environment for interactive use (PATH entries are covered by apt alternatives;
# these variables simply make the toolchains explicit).
export GOPATH="$HOME/go"
export JAVA_HOME="${JAVA_HOME:-/opt/java/temurin-26}"