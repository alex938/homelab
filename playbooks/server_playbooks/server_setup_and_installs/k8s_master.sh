#!/usr/bin/env bash

read -s -p "Vault password: " vault_pass
echo  

temp_vault_file=$(mktemp)
chmod 600 "${temp_vault_file}"

echo "${vault_pass}" > "${temp_vault_file}"

ansible-playbook setup_server_base.yml --limit k8s --vault-password-file "${temp_vault_file}"
ansible-playbook qemu_agent_install.yml --limit k8s --vault-password-file "${temp_vault_file}"
ansible-playbook install_k8s_worker.yml --limit kworkers --vault-password-file "${temp_vault_file}"
ansible-playbook install_k8s_control.yml --limit kcontrollers --vault-password-file "${temp_vault_file}"
sleep 30
ansible-playbook reboot.yml --limit k8s --vault-password-file "${temp_vault_file}"

rm -f "${temp_vault_file}"
