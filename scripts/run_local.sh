#!/usr/bin/env bash
# scripts/run_local.sh - Automated local runner for deployment and testing
set -euo pipefail

export SRL_USER="${SRL_USER:-admin}"
export SRL_PASSWORD="${SRL_PASSWORD:-NokiaSrl1!}"
export FRR_USER="${FRR_USER:-root}"
export FRR_PASSWORD="${FRR_PASSWORD:-frr}"

echo "=================================================="
echo " [0/5] Installing Ansible collections...         "
echo "=================================================="
ansible-galaxy collection install -r ansible/requirements.yml

echo "=================================================="
echo " [1/5] Deploying Containerlab Virtual Topology... "
echo "=================================================="
sudo -E clab deploy -t topology/topology.clab.yml

echo "Waiting for SR Linux JSON-RPC readiness..."
for i in 1 2 3 4 5 6; do
  sleep 20
  echo "Readiness probe attempt $i..."
  if curl -sf -u "$SRL_USER:$SRL_PASSWORD" \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"get","params":{"commands":[{"path":"/system/information/version","datastore":"state"}]}}' \
    http://172.20.20.11/jsonrpc; then
    break
  fi
done

echo "=================================================="
echo " [2/5] Running Ansible Configuration (Run 1)...   "
echo "=================================================="
ansible-playbook -i ansible/inventories/hosts.ini ansible/site.yml

echo "=================================================="
echo " [3/5] Verifying Ansible Idempotency (Run 2)...   "
echo "=================================================="
OUTPUT=$(ansible-playbook -i ansible/inventories/hosts.ini ansible/site.yml)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -qE "changed=0.*unreachable=0.*failed=0"; then
    echo ">>> Idempotency check PASSED (0 changed)."
else
    echo ">>> Idempotency check FAILED: Changes detected on second execution!"
    exit 1
fi

echo "=================================================="
echo " [4/5] Executing Cisco pyATS Verification Suite..."
echo "=================================================="
cd pyats
pyats run job test_job.py --testbed-file testbed.yml
cd ..

echo "=================================================="
echo " [5/5] All stages PASSED successfully!            "
echo "=================================================="

