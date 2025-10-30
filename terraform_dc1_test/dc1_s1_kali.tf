variable "create_dc1_s1_kali_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "dc1_s1_kali" {
  count       = var.create_dc1_s1_kali_vm ? 1 : 0
  name        = "DC1S1Kali"
  desc        = "dc1s1kali"
  vmid        = 1500
  target_node = var.node1

  agent       = 1
  clone       = var.student_kali_template
  cores       = var.student_kali_cores
  sockets     = var.student_kali_sockets
  cpu         = "host"
  memory      = var.student_kali_memory
  full_clone  = true

  ciuser     = "kali"
  cipassword = var.student_kali_cipassword
  sshkeys    = var.student_kali_sshkey
  ipconfig0  = "ip=192.168.3.1/24,gw=192.168.3.254,dns=192.168.3.254"

  scsihw = "virtio-scsi-single"

  disk {
    storage = "data2"
    type    = "disk"
    size    = var.student_kali_disk_size     
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

  network {
    model   = "virtio"
    bridge  = "DC1_S1_1"
    macaddr = "02:00:BB:BB:DD:01"
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
