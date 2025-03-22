variable "create_tkw1_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "tkw1" {
    count       = var.create_tkw1_vm ? 1 : 0
    name        = "tkw1.labjunkie.org"
    desc        = "tkw1.labjunkie.org"
    vmid        = "602"
    target_node = "d720"
    onboot      = true

    depends_on = [proxmox_vm_qemu.tkubecontrol1]

    agent       = 1
    clone       = "ubuntubase2"
    cores       = 2
    sockets     = 2
    cpu         = "host"
    memory      = 2048
    full_clone  = true

    scsihw = "virtio-scsi-single"

    disk {
        storage = "data2"
        type    = "disk"
        size    = "100G"     
        slot    = "scsi0"    
        format  = "qcow2"
    }

    disk {
        storage = "data2"
        type    = "cloudinit"
        slot    = "scsi1"
        format  = "qcow2"
    }

    bootdisk    = "scsi0"
    os_type     = "cloud-init"
    ciuser      = "alex"
    cipassword  = "$6$c/lkMtwWENjZ1QiM$x0tkiAz1PnVcKgajgqTPSvW.dvR.jwodsyQr.XSrG2SwVKJ1JzhAabQoQMz2MfZgDmipAFA46L65ckOVxszHA0" #"alex" changed via ansible scripts
    ipconfig0   = "ip=192.168.2.231/24,gw=192.168.2.1,dns=192.168.2.12,172.20.1.2"

    network {
        model  = "virtio"
        bridge = "vmbr0"
        firewall = false
    }
}