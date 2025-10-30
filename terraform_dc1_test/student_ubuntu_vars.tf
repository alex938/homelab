variable "student_ubuntu_template" {
  type        = string
  default     = "ubuntuci"
  description = "Template for the student ubuntu vms"
}

variable "student_ubuntu_memory" {
  type        = number
  default     = 4096
  description = "RAM allocated to the ubuntu VM MB"
}

variable "student_ubuntu_cores" {
  type        = number
  default     = 4
  description = "Number of CPU cores"
}

variable "student_ubuntu_sockets" {
  type        = number
  default     = 1
  description = "Number of CPU sockets"
}

variable "student_ubuntu_disk_size" {
  type        = string
  default     = "30G"
  description = "Size of the ubuntu VM disk"
}

variable "student_ubuntu_ciuser" {
  type        = string
  default     = "admin1"
  description = "Username for the student ubuntu VM"
}

variable "student_ubuntu_cipassword" {
  type        = string
  default     = "$6$H.CqWzNdudC07Kd1$Ytbyoncodh.ioXyUYZUMq8cUbd0Sf7HoHVMjiNRa2BOlZkbj1KuCwOTgv.uWLFQFsOMyay6EZAvOEEdcIeCJk/"
  description = "Hashed password for the ubuntu VM"
  sensitive   = true
}

variable "student_ubuntu_sshkey" {
  type        = string
  default     = <<EOF
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIFIQ5igyscNkCUXT2uVEsXKp335yIM/63fcr1EnfY9W
EOF
  description = "SSH key for ubuntu VM"
}