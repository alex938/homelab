variable "create_si_vm" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "si" {
    count       = var.create_si_vm ? 1 : 0
    name        = "si.labjunkie.org"
    desc        = "si.labjunkie.org"
    vmid        = "510"
    target_node = "ms01"
    onboot      = true

    agent       = 1
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
    ipconfig0   = "ip=192.168.2.60/24,gw=192.168.2.1,dns=192.168.2.12,172.20.1.2"

    network {
        model  = "virtio"
        bridge = "vmbr0"
        firewall = false
    }

    lifecycle {
        ignore_changes = [
        ciuser,
        cipassword,
        ipconfig0,
        bootdisk,
        network,
        vm_state,
        disk]
    }
}