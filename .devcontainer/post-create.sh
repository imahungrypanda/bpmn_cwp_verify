#!/bin/sh

# Amazon Linux 2023 uses microdnf instead of apt
# Install JRE for ANTLRv4 tools and graphviz binaries
sudo microdnf -y update
sudo microdnf -y install java-17-amazon-corretto graphviz
sudo microdnf -y clean all

# Spin is already installed in /opt/bin/spin from the base Dockerfile stage
# Verify it's available
spin -V || echo "Warning: Spin not found in PATH"

# Upgrade pip
pip install --upgrade pip

# Install pyright for pre-commit
pip install pyright

# Install the package
pip install --user --editable ".[dev]"

# Install pyright
npm install -g pyright

# Install pre-commit
pre-commit install

# --- devcontainer niceties (dircolors, aliases) ---
# Append color support to ~/.bashrc so it persists in interactive shells.
# post-create.sh runs in its own subshell, so aliases and exports set here
# would not survive into new terminal sessions without writing them to a
# shell profile.
cat >> ~/.bashrc << 'EOF'

# Color support (added by devcontainer post-create)
export LS_COLORS='di=34:ln=36:so=35:pi=33:ex=32:bd=33;01:cd=33;01:su=31;01:sg=31;01:tw=34;01:ow=34;01:'
alias ls='ls --color=auto'
alias ll='ls -alhF --color=auto'
alias la='ls -A'
alias grep='grep --color=auto'
alias diff='diff --color=auto'
alias ip='ip -color=auto'
export LESS='-R'
export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'
EOF
