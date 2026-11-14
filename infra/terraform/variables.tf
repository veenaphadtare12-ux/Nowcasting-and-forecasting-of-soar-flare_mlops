variable "region" {
  description = "AWS region"
  type        = string
  default     = "ap-south-1" # Mumbai
}

variable "instance_type" {
  description = "VM size: the API image loads 5 models; 2 vCPU / 8 GB runs the whole stack comfortably"
  type        = string
  default     = "t3.large"
}

variable "disk_gb" {
  description = "Root disk size (images ~5 GB + volumes)"
  type        = number
  default     = 40
}

variable "ssh_public_key" {
  description = "Public half of the deploy key (the private half goes into the GitHub secret DEPLOY_SSH_KEY)"
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "Who may SSH in. GitHub-hosted runners use changing IPs, so CD needs 0.0.0.0/0 or a self-hosted runner"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
