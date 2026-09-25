#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
umask 077
export FRR_SSH_KEY="${FRR_SSH_KEY:-${ROOT_DIR}/.lab/ssh/id_ed25519}"
KEY_DIR="${ROOT_DIR}/.lab/ssh"
FRR_DIR="${ROOT_DIR}/.lab/frr"

mkdir -p "${KEY_DIR}" "${FRR_DIR}"
if [[ ! -f "${FRR_SSH_KEY}" ]]; then
  ssh-keygen -t ed25519 -N '' -f "${FRR_SSH_KEY}" -C containerlab-lab-key
fi
chmod 600 "${FRR_SSH_KEY}"
install -m 0644 "${FRR_SSH_KEY}.pub" "${KEY_DIR}/authorized_keys"
install -m 0644 "${ROOT_DIR}/ansible/roles/frr_bgp/templates/daemons" "${FRR_DIR}/daemons"
install -m 0644 "${ROOT_DIR}/ansible/roles/frr_bgp/templates/vtysh.conf" "${FRR_DIR}/vtysh.conf"
printf 'frr defaults traditional\nservice integrated-vtysh-config\n!\n' > "${FRR_DIR}/frr.conf"
# The file is bind-mounted into the FRR container before Ansible changes it.
# It must be readable by the container's frr user on the first boot.
chmod 0644 "${FRR_DIR}/frr.conf"
printf 'Prepared lab SSH key and FRR files under %s\n' "${ROOT_DIR}/.lab"
