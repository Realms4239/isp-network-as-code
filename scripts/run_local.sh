#!/usr/bin/env bash
# scripts/run_local.sh - Automated local runner for deployment and testing
set -euo pipefail

echo "=================================================="
echo " [1/5] Deploying Containerlab Virtual Topology... "
echo "=================================================="
sudo clab deploy -t topology/topology.clab.yml

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
