variable "create_dev2_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "dev2_labjunkie_org" {
    count       = var.create_dev2_vm ? 1 : 0
    name        = "dev2.labjunkie.org"
    desc        = "dev2.labjunkie.org"
    vmid        = "100"
    target_node = "ms01"

    agent       = 0
    clone       = "ubuntubase"
    cores       = 4
    sockets     = 2
    cpu         = "host"
    memory      = 4096
    full_clone  = true

    scsihw = "virtio-scsi-single"

    disk {
        storage = "data1"
        type    = "disk"
        size    = "100G"     
        slot    = "scsi0"    
        format  = "qcow2"
    }

    disk {
        storage = "data1"
        type    = "cloudinit"
        slot    = "scsi1"
        format  = "qcow2"
    }

    bootdisk    = "scsi0"
    os_type     = "cloud-init"
    ciuser      = "alex"
    cipassword  = "$6$c/lkMtwWENjZ1QiM$x0tkiAz1PnVcKgajgqTPSvW.dvR.jwodsyQr.XSrG2SwVKJ1JzhAabQoQMz2MfZgDmipAFA46L65ckOVxszHA0" #"alex" changed via ansible scripts
    ipconfig0   = "ip=192.168.2.47/24,gw=192.168.2.1,dns=192.168.2.12,172.20.1.2"

    network {
        model  = "virtio"
        bridge = "vmbr0"
        firewall = true
    }
}