variable "create_shf_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "shf" {
    count       = var.create_shf_vm ? 1 : 0
    name        = "shf.labjunkie.org"
    desc        = "shf.labjunkie.org"
    vmid        = "511"
    target_node = "aio1"

    agent       = 1
    clone       = "ubuntubase2"
    cores       = 2
    sockets     = 2
    cpu         = "host"
    memory      = 2048
    full_clone  = true

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
        slot    = "scsi1"
        format  = "raw" #Changed from "qcow2" to "raw" to avoid error proxmox when using local-lvm storage, Proxmox stores VM disks as raw volumes
    }

    bootdisk    = "scsi0"
    os_type     = "cloud-init"
    ciuser      = "alex"
    cipassword  = "$6$c/lkMtwWENjZ1QiM$x0tkiAz1PnVcKgajgqTPSvW.dvR.jwodsyQr.XSrG2SwVKJ1JzhAabQoQMz2MfZgDmipAFA46L65ckOVxszHA0" #"alex" changed via ansible scripts
    ipconfig0   = "ip=192.168.2.61/24,gw=192.168.2.1,dns=192.168.2.12,172.20.1.2"

    network {
        model  = "virtio"
        bridge = "vmbr0"
        firewall = true
    }
}