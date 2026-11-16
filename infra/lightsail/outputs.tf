output "public_ip" {
  description = "Static IP: point veena-flare.duckdns.org here and put it into the GitHub secret DEPLOY_HOST"
  value       = aws_lightsail_static_ip.flare.ip_address
}

output "ssh" {
  value = "ssh -i ~/.ssh/flare_deploy ubuntu@${aws_lightsail_static_ip.flare.ip_address}"
}
