variable "create_command_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "command" {
  count       = var.create_command_vm ? 1 : 0
  name        = "command.training.org"
  desc        = "command.training.org"
  vmid        = 1005
  target_node = "d720"

  agent       = 1
  clone       = "command"
  cores       = 8
  sockets     = 1
  cpu         = "host"
  memory      = 16384
  full_clone  = true

  scsihw = "virtio-scsi-single"

  disk {
    storage = "data2"
    type    = "disk"
    size    = "200G"
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
  ciuser     = "command"
  cipassword = "$6$XrZ7jkstashboRpG$GqX9fahEugi5qhU47YLajJzgF.8SHLDiaT.izClx4Srw9G5rxlFuFKPCWDU4noi7lYZGwnq47a.n0MV6Mgk/C0" #changed in ansible
  ipconfig1  = "ip=172.16.1.10/24,gw=172.16.1.1,dns=172.16.1.1"
  sshkeys    = <<EOF
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKyBpICpsW8z8x6O3u0uhggrDlnyk/mXNm5s4sG8R+Tv
EOF

  lifecycle {
      ignore_changes = [
      ciuser,
      cipassword,
      ipconfig0,
      ipconfig1,
      bootdisk,
      disk]
  }
}