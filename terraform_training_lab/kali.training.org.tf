variable "kali_vm_count" {
  type    = number
  default = 10
}

resource "proxmox_vm_qemu" "kali" {
  count       = var.kali_vm_count

  name        = "kali${count.index + 1}.training.org"
  desc        = "kali${count.index + 1}.training.org"
  vmid        = 1010 + count.index
  target_node = "d720"

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
  cipassword = "$6$kD39IcZb$2kpWUkTgJ2vC8BL8IXM3lvzYWe/B6QsUpK8b92VoqCIgbRgHzF3UR/uzf8mFghIWUbppnF5/yQfWeNdSKj.UO."
  ipconfig0  = "ip=172.16.1.${50 + count.index}/24,gw=172.16.1.1,dns=172.16.1.1"
}
