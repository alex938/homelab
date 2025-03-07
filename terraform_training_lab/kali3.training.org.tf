variable "create_k3_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "kali3" {
  count       = var.create_k3_vm ? 1 : 0
  name        = "kali3.training.org"
  desc        = "kali3.training.org"
  vmid        = 1013
  target_node = "d720"

  depends_on = [proxmox_vm_qemu.kali2]

  agent       = 0
  clone       = "kali"
  cores       = 4
  sockets     = 1
  cpu         = "host"
  memory      = 4096
  full_clone  = true

  scsihw = "virtio-scsi-single"

  disk {
      storage = "data2"
      type    = "disk"
      size    = "50G"     
      slot    = "scsi0"    
      format  = "raw"
  }

  disk {
      storage = "data2"
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
  cipassword = "$6$9lSm9fLFlVjuApgE$cpHt0M3KvLHoeA/Bxpd7hIM.8lAX4ogdQudxM8x0mwKKJrnZeBG8UEMVYSy2e63nYgCMu1FBNunBND08/YbbE1"
  sshkeys    = <<EOF
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKOTN5xB9rOGAkP1GS2MWPpnUkPD5qig3fAr3bEZFwmt
EOF
  ipconfig0  = "ip=172.16.1.53/24,gw=172.16.1.1,dns=172.16.1.1"

  network {
    model  = "virtio"
    bridge = "kali_net"
    macaddr = "02:00:AA:BB:CC:03"
  }
}
