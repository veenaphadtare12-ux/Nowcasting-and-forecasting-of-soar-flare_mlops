variable "region" {
  description = "Lightsail region (Mumbai)"
  type        = string
  default     = "ap-south-1"
}

variable "aws_profile" {
  description = "AWS CLI profile with Lightsail permissions"
  type        = string
  default     = "flare"
}

variable "bundle_id" {
  description = "Lightsail plan: 4 GB RAM / 2 vCPU runs the whole stack (see docs/DEPLOY_STEPS.md for prices)"
  type        = string
  default     = "medium_3_0"
}

variable "blueprint_id" {
  description = "Operating system image"
  type        = string
  default     = "ubuntu_24_04"
}

variable "ssh_public_key" {
  description = "Public half of the deploy key (the private half goes only into the GitHub secret DEPLOY_SSH_KEY)"
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "Who may SSH in. GitHub-hosted runners use changing IPs, so CD needs 0.0.0.0/0 (key-only login)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
