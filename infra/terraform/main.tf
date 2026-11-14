# One small VM with k3s for the flare product (written, validated in CI, NOT applied).
# What it creates: an SSH key pair from your public key, a security group (SSH from your IP only, HTTP/HTTPS from
# anywhere), an Ubuntu 24.04 instance whose cloud-init installs k3s, a deploy user and kubeconfig, and an Elastic IP.
# After `terraform apply`: put the output public_ip into the GitHub secret DEPLOY_HOST, "deploy" into DEPLOY_USER,
# and the matching private key into DEPLOY_SSH_KEY (docs/RUNBOOK.md#continuous-deployment).

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project = "flare"
      managed = "terraform"
    }
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_key_pair" "deploy" {
  key_name   = "flare-deploy"
  public_key = var.ssh_public_key
}

resource "aws_security_group" "flare" {
  name        = "flare-k3s"
  description = "flare: SSH from the admin IP, web from anywhere"

  ingress {
    description = "SSH (admin and GitHub Actions deploy; widen only if needed)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidrs
  }
  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "k3s" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.deploy.key_name
  vpc_security_group_ids = [aws_security_group.flare.id]

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_public_key = var.ssh_public_key
  })

  root_block_device {
    volume_size = var.disk_gb
    volume_type = "gp3"
    encrypted   = true
  }
  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }
  tags = {
    Name = "flare-k3s"
  }
}

resource "aws_eip" "k3s" {
  instance = aws_instance.k3s.id
  domain   = "vpc"
}
