output "public_ip" {
  description = "Put this into the GitHub secret DEPLOY_HOST"
  value       = aws_eip.k3s.public_ip
}

output "website" {
  value = "http://${aws_eip.k3s.public_ip}"
}

output "ssh" {
  value = "ssh deploy@${aws_eip.k3s.public_ip}"
}
