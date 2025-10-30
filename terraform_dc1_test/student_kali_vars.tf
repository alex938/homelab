variable "student_kali_template" {
  type        = string
  default     = "kalici"
  description = "Template for the student Kali VM"
}

variable "student_kali_memory" {
  type        = number
  default     = 4096
  description = "RAM allocated to the Kali VM MB"
}

variable "student_kali_cores" {
  type        = number
  default     = 4
  description = "Number of CPU cores"
}

variable "student_kali_sockets" {
  type        = number
  default     = 1
  description = "Number of CPU sockets"
}

variable "student_kali_disk_size" {
  type        = string
  default     = "50G"
  description = "Size of the Kali VM disk"
}

variable "student_kali_ciuser" {
  type        = string
  default     = "kali"
  description = "Username for the student Kali VM"
}

variable "student_kali_cipassword" {
  type        = string
  default     = "$6$.m0HddxTvUyXJnJr$wRecs27HxFsCudLdUsrJ90tWwssBINY76IEe.b0HViRMfWTS/YxvjVyMV6Etul6I6tz8tdktyGbkQ9kiA9tw01"
  description = "Hashed password for the Kali VM"
  sensitive   = true
}

variable "student_kali_sshkey" {
  type        = string
  default     = <<EOF
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKOTN5xB9rOGAkP1GS2MWPpnUkPD5qig3fAr3bEZFwmt
EOF
  description = "SSH key for student Kali VM"
}