variable "create_wan_side_redirector" {
  type    = bool
  default = true
}

resource "proxmox_vm_qemu" "wan_side_redirector" {
    count       = var.create_wan_side_redirector ? 1 : 0
    name        = "wan-side-redirector"
    desc        = "wan_side_redirector"
    vmid        = "2102"
    target_node = "d720"
    onboot      = true

    depends_on = [proxmox_vm_qemu.lan_side_sliver]

    agent       = 1
    clone       = "ubuntubase2"
    cores       = 2
    sockets     = 2
    cpu         = "host"
    memory      = 4096
    full_clone  = true

    scsihw = "virtio-scsi-single"

    disk {
        storage = "data2"
        type    = "disk"
        size    = "100G"     
        slot    = "scsi0"    
        format  = "raw"
    }

    disk {
        storage = "data2"
        type    = "cloudinit"
        slot    = "scsi1"
        format  = "raw" #Changed from "qcow2" to "raw" to avoid error proxmox when using local-lvm storage, Proxmox stores VM disks as raw volumes
    }

    bootdisk    = "scsi0"
    os_type     = "cloud-init"
    ciuser      = "alex"
    cipassword  = "$6$c/lkMtwWENjZ1QiM$x0tkiAz1PnVcKgajgqTPSvW.dvR.jwodsyQr.XSrG2SwVKJ1JzhAabQoQMz2MfZgDmipAFA46L65ckOVxszHA0" #"alex" changed via ansible scripts
    ipconfig0   = "ip=192.168.2.54/24,gw=192.168.2.1,dns=192.168.2.12,172.20.1.2"
    ipconfig1   = "ip=172.30.1.1/24,gw=172.30.1.254"

    network {
        model  = "virtio"
        bridge = "vmbr0"
        firewall = false
    }

    network {
        model  = "virtio"
        bridge = "WAN_SIDE"
        firewall = false
    }

    lifecycle {
        ignore_changes = [
        ciuser,
        cipassword,
        ipconfig0,
        bootdisk,
        network,
        disk,
        vm_state]
    } 
}