#!/usr/bin/env bash
# scripts/run_local.sh - Automated local runner for deployment and testing
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOPOLOGY="${ROOT_DIR}/topology/topology.clab.yml"
ARTIFACTS="${ROOT_DIR}/artifacts"
REDACTED_ARTIFACTS="${ROOT_DIR}/artifacts-redacted"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
EVENTS="${ARTIFACTS}/events.jsonl"
mkdir -p "${ARTIFACTS}"
cd "${ROOT_DIR}"

export SRL_USER="${SRL_USER:-admin}"
: "${SRL_PASSWORD:?Set SRL_PASSWORD before running the lab}"
export SRL_PASSWORD
export FRR_USER="${FRR_USER:-root}"
export FRR_SSH_KEY="${FRR_SSH_KEY:-${ROOT_DIR}/.lab/ssh/id_ed25519}"
# Single source of truth for collection resolution. Exported once here so every
# ansible-galaxy, ansible-playbook, and ansible-lint call below inherits it.
# ansible.cfg deliberately does not set collections_path, because a value there
# takes precedence over this variable.
export ANSIBLE_COLLECTIONS_PATH="${ROOT_DIR}/ansible/collections"

for command in bash clab sudo ansible-playbook ansible-galaxy pyats python3 ssh-keygen install; do
  command -v "${command}" >/dev/null || { echo "ERROR: ${command} is not installed." >&2; exit 1; }
done
bash "${ROOT_DIR}/scripts/prepare_lab.sh"

cleanup() {
  local exit_code=$?
  set +e
  python3 scripts/lab_evidence.py event --output "${EVENTS}" --run-id "${RUN_ID}" --stage teardown --status started
  sudo clab destroy -t "${TOPOLOGY}" --cleanup
  python3 scripts/lab_evidence.py event --output "${EVENTS}" --run-id "${RUN_ID}" --stage teardown --status passed
  python3 scripts/lab_evidence.py redact --root "${ARTIFACTS}" --output "${REDACTED_ARTIFACTS}" --secret-env SRL_PASSWORD
  python3 scripts/lab_evidence.py manifest --root "${REDACTED_ARTIFACTS}" --output "${REDACTED_ARTIFACTS}/manifest.json" --run-id "${RUN_ID}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

record_stage() {
  local stage="$1"
  local status="$2"
  shift 2
  python3 scripts/lab_evidence.py event \
    --output "${EVENTS}" --run-id "${RUN_ID}" --stage "${stage}" --status "${status}" "$@"
}

record_stage contract started
echo "[1/7] Validating repository contracts..."
python3 scripts/validate_contract.py
record_stage contract passed

record_stage collections started
echo "[2/7] Installing pinned Ansible collections..."
# ansible.cfg deliberately does not set collections_path: a value there
# overrides this variable, which previously made collection resolution depend
# on the config file and broke the syntax check on CI. One source of truth here.
ANSIBLE_COLLECTIONS_PATH="${ROOT_DIR}/ansible/collections" \
  ansible-galaxy collection install -r ansible/requirements.yml -p "${ROOT_DIR}/ansible/collections"
# Fail here, naming the problem, instead of letting it surface later as an
# opaque playbook or lint error.
for c in nokia.srlinux ansible.netcommon ansible.utils; do
  test -d "${ROOT_DIR}/ansible/collections/ansible_collections/${c%%.*}/${c#*.}" \
    || { echo "ERROR: missing collection ${c}" >&2; exit 1; }
done
record_stage collections passed

record_stage deploy started
echo "[3/7] Deploying Containerlab topology..."
sudo clab deploy -t "${TOPOLOGY}"
sudo clab inspect --all --format json > "${ARTIFACTS}/containerlab-inspect.json"
record_stage deploy passed

record_stage readiness started
python3 scripts/wait_for_lab.py --plan "${ROOT_DIR}/data/lab.yml" --attempts 30 --delay 10
record_stage readiness passed

record_stage ansible-run-1 started
echo "[4/7] Running Ansible configuration (run 1)..."
(cd "${ROOT_DIR}/ansible" && \
  ANSIBLE_CONFIG="${ROOT_DIR}/ansible/ansible.cfg" \
  ANSIBLE_STDOUT_CALLBACK=lab_json \
  ansible-playbook -i inventories/hosts.ini site.yml) > "${ARTIFACTS}/ansible-run-1.json"
record_stage ansible-run-1 passed

record_stage ansible-run-2 started
echo "[5/7] Verifying exact Ansible idempotency (run 2)..."
set +e
(cd "${ROOT_DIR}/ansible" && \
  ANSIBLE_CONFIG="${ROOT_DIR}/ansible/ansible.cfg" \
  ANSIBLE_STDOUT_CALLBACK=lab_json \
  ansible-playbook -i inventories/hosts.ini site.yml) > "${ARTIFACTS}/ansible-run-2.json"
run2_rc=$?
set -e
if [[ ${run2_rc} -ne 0 ]]; then
  cat "${ARTIFACTS}/ansible-run-2.json"
  record_stage ansible-run-2 failed --duration-ms 0
  exit "${run2_rc}"
fi
python3 scripts/check_ansible_result.py "${ARTIFACTS}/ansible-run-2.json" \
  --plan "${ROOT_DIR}/data/lab.yml" --require-idempotent \
  --report "${ARTIFACTS}/ansible-check-2.json" --run-id "${RUN_ID}"
record_stage ansible-run-2 passed

record_stage pyats started
echo "[6/7] Running pyATS verification..."
(cd pyats && pyats run job test_job.py --testbed-file testbed.yml) 2>&1 | tee "${ARTIFACTS}/pyats.log"
record_stage pyats passed

echo "[7/7] All stages passed; teardown runs from the EXIT trap."
