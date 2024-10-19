variable "create_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "kubecontrol1" {
    count       = var.create_vm ? 1 : 0
    name        = "kubecontrol1"
    desc        = "kubernetes control server 1"
    vmid        = "201"
    target_node = "ms01"

    agent       = 1
    clone       = "ubuntubase"
    cores       = 2
    sockets     = 2
    cpu         = "host"
    memory      = 2048

    scsihw = "virtio-scsi-single"

    disk {
        storage = "data1"
        type    = "disk"
        size    = "100G"
        slot    = "scsi0"
        format  = "qcow2"
    }

    os_type     = "cloud-init"
    ciuser      = "alex"
    cipassword  = "$6$c/lkMtwWENjZ1QiM$x0tkiAz1PnVcKgajgqTPSvW.dvR.jwodsyQr.XSrG2SwVKJ1JzhAabQoQMz2MfZgDmipAFA46L65ckOVxszHA0" #"alex" changed via ansible scripts
    ipconfig0   = "ip=192.168.2.60/24,gw=192.168.2.1"
    nameserver  = "192.168.2.1,172.20.1.2"

    network {
        model  = "virtio"
        bridge = "vmbr0"
        firewall = true
    }
}