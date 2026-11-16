# One AWS Lightsail server that runs the Docker Compose stack behind Caddy (automatic HTTPS for the DuckDNS name).
# EC2 is denied for this account by its organisation's service control policy; Lightsail is allowed (2026-11-16).
# What it creates: an SSH key pair (from your public key), an Ubuntu 24.04 instance whose launch script installs Docker,
# a static IP attached to it (free while attached), and a firewall with ports 22, 80 and 443 only.
#   terraform init && terraform plan && terraform apply     (creates a billable server: see docs/DEPLOY_STEPS.md)

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
}

resource "aws_lightsail_key_pair" "deploy" {
  name       = "flare-deploy"
  public_key = var.ssh_public_key
}

resource "aws_lightsail_instance" "flare" {
  name              = "flare"
  availability_zone = "${var.region}a"
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.deploy.name
  user_data         = file("${path.module}/launch.sh")
  tags = {
    project = "flare"
  }
}

resource "aws_lightsail_static_ip" "flare" {
  name = "flare-ip"
}

resource "aws_lightsail_static_ip_attachment" "flare" {
  static_ip_name = aws_lightsail_static_ip.flare.name
  instance_name  = aws_lightsail_instance.flare.name
}

resource "aws_lightsail_instance_public_ports" "flare" {
  instance_name = aws_lightsail_instance.flare.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_cidrs
  }
  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
    cidrs     = ["0.0.0.0/0"]
  }
  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }
  port_info {
    protocol  = "udp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }
}
