#!/usr/bin/env bash
# The hosted Ubuntu runners can have an empty regional mirror list. Use the
# official signed AMD64 Noble indexes for this job, including the fonts in universe.
set -euo pipefail
sudo tee /etc/apt/workbench-noble.sources >/dev/null <<'SOURCES'
Types: deb
URIs: https://archive.ubuntu.com/ubuntu
Suites: noble noble-updates
Components: main restricted universe multiverse
Architectures: amd64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: https://security.ubuntu.com/ubuntu
Suites: noble-security
Components: main restricted universe multiverse
Architectures: amd64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SOURCES
sudo mkdir -p /etc/apt/workbench-sourceparts
sudo tee /etc/apt/apt.conf.d/99workbench-sources >/dev/null <<'CONFIG'
Dir::Etc::sourcelist "/etc/apt/workbench-noble.sources";
Dir::Etc::sourceparts "/etc/apt/workbench-sourceparts";
Acquire::Retries "3";
APT::Update::Error-Mode "any";
CONFIG
