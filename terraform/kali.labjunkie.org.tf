variable "create_kali_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "kali1" {
  count       = var.create_kali_vm ? 1 : 0
  name        = "kali.labjunkie.org"
  desc        = "kali.labjunkie.org"
  vmid        = 1100
  target_node = "aio1"

  agent       = 1
  clone       = "kalicii"
  cores       = 4
  sockets     = 1
  cpu         = "host"
  memory      = 6000
  full_clone  = true
  onboot      = true

  scsihw = "virtio-scsi-single"

  disk {
      storage = "local-lvm"
      type    = "disk"
      size    = "100G"     
      slot    = "scsi0"    
      format  = "raw"
  }

  disk {
      storage = "local-lvm"
      type    = "cloudinit"
      slot    = "ide2"
  }

  serial {
      id   = 0
      type = "socket"
  }

  bootdisk   = "scsi0"
  os_type    = "cloud-init"
  ciuser     = "kali"
  cipassword = "$6$9lSm9fLFlVjuApgE$cpHt0M3KvLHoeA/Bxpd7hIM.8lAX4ogdQudxM8x0mwKKJrnZeBG8UEMVYSy2e63nYgCMu1FBNunBND08/YbbE1" #kali changed via ansible scripts
  ipconfig0  = "ip=192.168.2.105/24,gw=192.168.2.1,dns=192.168.2.12"
  sshkeys    = <<EOF
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKOTN5xB9rOGAkP1GS2MWPpnUkPD5qig3fAr3bEZFwmt
EOF

    network {
        model  = "virtio"
        bridge = "vmbr0"
        firewall = false
    }

  provisioner "local-exec" {
    command = <<-EOT
      sleep 180
      curl -s -k -X POST \
        -H "Authorization: PVEAPIToken=${var.proxmox_api_token_id}=${var.proxmox_api_token_secret}" \
        "${var.proxmox_api_url}/nodes/aio1/qemu/1100/status/stop"
      sleep 5
      curl -s -k -X POST \
        -H "Authorization: PVEAPIToken=${var.proxmox_api_token_id}=${var.proxmox_api_token_secret}" \
        "${var.proxmox_api_url}/nodes/aio1/qemu/1100/status/start"
    EOT
  }

  lifecycle {
    ignore_changes = [
    ciuser,
    cipassword,
    ipconfig0,
    bootdisk,
    disk]
  }
}