variable "create_dc1_s1_dns_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "dc1_s1_dns" {
  count       = var.create_dc1_s1_dns_vm ? 1 : 0
  name        = "DC1S1DNS"
  desc        = "DC1S1DNS"
  vmid        = 1503
  target_node = var.node1

  agent      = 1
  clone      = var.student_ubuntu_template   # this template (from your screenshot) is fine
  full_clone = true

  cpu     = "host"
  cores   = var.student_ubuntu_cores
  sockets = var.student_ubuntu_sockets
  memory  = var.student_ubuntu_memory
  scsihw  = "virtio-scsi-single"

  ciuser     = "admin1"
  cipassword = var.student_ubuntu_cipassword
  sshkeys    = var.student_ubuntu_sshkey
  ipconfig0  = "ip=192.168.10.108/24,gw=192.168.10.254,dns=192.168.10.254"

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
    bridge  = "DC1_S1_2"
    macaddr = "02:00:12:DD:DD:01"
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