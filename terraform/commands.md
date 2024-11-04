# Proxmox VM Deployment with Terraform

## Setup

1. **Create Credentials File**:  
   Set up `credentials.auto.tfvars` with the Proxmox API credentials. Replace the placeholder values as necessary.

   ```hcl
   proxmox_api_url         = "https://192.168.2.35:8006/api2/json"
   proxmox_api_token_id    = ""
   proxmox_api_token_secret = ""
   ```

2. **Setting up state, creating and destroying infrastructure**:  
    ```hcl
    terraform init
    terraform plan

    Destroy:
    terraform apply -var="create_dev2_vm=false" -auto-approve -target=proxmox_vm_qemu.dev2_labjunkie_org

    Create:
    terraform apply -var="create_dev2_vm=true" -auto-approve -target=proxmox_vm_qemu.dev2_labjunkie_org
    ```
