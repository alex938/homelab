variable "create_dc1_s1_secon_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "dc1_s1_secon" {
  count       = var.create_dc1_s1_secon_vm ? 1 : 0
  name        = "DC1S1SECON"
  desc        = "DC1S1SECON"
  vmid        = 1504
  target_node = var.node1

  agent      = 1
  clone      = var.student_ubuntu_template
  full_clone = true

  cpu     = "host"
  cores   = var.student_ubuntu_cores
  sockets = var.student_ubuntu_sockets
  memory  = var.student_ubuntu_memory
  scsihw  = "virtio-scsi-single"

  ciuser     = "admin1"
  cipassword = var.student_ubuntu_cipassword
  sshkeys    = var.student_ubuntu_sshkey

  ipconfig0  = "ip=172.16.2.30/24,gw=172.16.2.254,dns=172.16.2.254"

  disk {
    storage = "data2"
    type    = "disk"
    size    = var.student_ubuntu_disk_size
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

  bootdisk = "scsi0"

  network {
    model   = "virtio"
    bridge  = "DC1_S1_3"
    macaddr = "02:00:05:11:DD:01"
  }

  network {
    model   = "virtio"
    bridge  = "DC1_S1_MIR"
    macaddr = "02:00:05:12:CC:02"
  }

  lifecycle {
    ignore_changes = [
      ciuser,
      cipassword,
      ipconfig0,
      bootdisk,
      disk
    ]
  }
}
