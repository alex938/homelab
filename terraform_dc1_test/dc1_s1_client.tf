variable "create_dc1_s1_client_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "dc1_s1_client" {
  count       = var.create_dc1_s1_client_vm ? 1 : 0
  name        = "DC1S1CLIENT"
  desc        = "DC1S1CLIENT"
  vmid        = 1502
  target_node = var.node1

  agent       = 1
  clone       = var.student_kali_template
  cores       = var.student_kali_cores
  sockets     = var.student_kali_sockets
  cpu         = "host"
  memory      = var.student_kali_memory
  full_clone  = true

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
  ciuser     = "kali"
  cipassword = var.student_kali_cipassword

  sshkeys = var.student_kali_sshkey
  
  ipconfig0 = "ip=192.168.10.1/24,gw=192.168.10.254,dns=192.168.10.254"

  network {
    model   = "virtio"
    bridge  = "DC1_S1_2"
    macaddr = "02:00:01:CC:DD:01"
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
