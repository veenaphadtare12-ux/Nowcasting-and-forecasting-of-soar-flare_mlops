# Deploy steps (waiting on you)

Status on 2026-11-14: **not deployed.** The repository has no `DEPLOY_HOST`, `DEPLOY_USER` or `DEPLOY_SSH_KEY` secret
(checked by name with `gh secret list`, repository and `production` environment). Everything else is ready: CD publishes
the images to GHCR on every green master build and on tags, and the GHCR packages are already **public** (an anonymous
pull token is granted), so no `GHCR_PULL_TOKEN` is needed.

## 1. Create the server (you)
Any provider works (AWS, Azure, DigitalOcean, Hetzner, a university VM). Requirements:
| Item | Value |
|---|---|
| OS | Ubuntu 24.04 LTS |
| Size | 2 vCPU, 8 GB RAM, 40 GB disk (the stack uses about 5 GB RAM; the API image is 2.4 GB) |
| Ports open | 22 (SSH), 80 (HTTP), 443 (HTTPS) |
| Public IP | a static/elastic IP (this becomes `DEPLOY_HOST`) |
| Budget alert | set one before creating anything (e.g. AWS Budgets / Azure Cost alerts at a small monthly limit); a t3.large-class VM costs roughly USD 60–70 per month if left running |
| Optional domain | a DNS A record pointing at the IP, for automatic HTTPS |

Option A, Terraform (AWS): `infra/terraform` creates exactly this (t3.large, ap-south-1, 40 GB encrypted disk, security
group 22/80/443, Elastic IP) and installs k3s with a `deploy` user. Review `terraform plan` before `apply`; it creates billable
resources.

Option B, by hand, on the new server:
```
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 600
sudo useradd -m -s /bin/bash deploy
sudo mkdir -p /home/deploy/.kube /home/deploy/.ssh
sudo cp /etc/rancher/k3s/k3s.yaml /home/deploy/.kube/config
sudo chown -R deploy:deploy /home/deploy/.kube /home/deploy/.ssh && sudo chmod 600 /home/deploy/.kube/config
sudo ln -sf /usr/local/bin/k3s /usr/local/bin/kubectl
```

## 2. Create a deploy key (you, on your PC)
```
ssh-keygen -t ed25519 -f flare_deploy -C "github-actions-deploy" -N ""
```
Put the content of `flare_deploy.pub` into `/home/deploy/.ssh/authorized_keys` on the server (Terraform: the variable
`ssh_public_key`). Keep `flare_deploy` (the private key) secret; it goes only into GitHub.

## 3. Add the repository secrets (you)
GitHub → the repository → Settings → Secrets and variables → Actions → New repository secret:
| Secret | Value | Required |
|---|---|---|
| `DEPLOY_HOST` | the server's public IP or DNS name | yes |
| `DEPLOY_USER` | `deploy` | yes |
| `DEPLOY_SSH_KEY` | the whole private key file `flare_deploy`, including the BEGIN/END lines | yes |
| `FLARE_API_KEYS` | a long random string (for `POST /predict`); without it `/predict` refuses every call | recommended |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin password (otherwise a random one is created) | optional |
| `SMTP_SMARTHOST`, `SMTP_FROM`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | alert e-mail through any SMTP relay (e.g. `smtp.gmail.com:587` with an app password) | optional |
| `GHCR_PULL_TOKEN` | only if you make the GHCR packages private again | not needed now |

## 4. Trigger the deployment (one action)
GitHub → Actions → **CD** → **Run workflow** (branch `master`), or from a terminal:
```
gh workflow run CD --ref master
```
What it does: build and push the images (git SHA + `master`), copy `k8s/`, `scripts/k8s/` and `monitoring/` to the server,
run `scripts/k8s/deploy.sh prod <sha>` (waits for every rollout; on any failure it runs `kubectl rollout undo` and the
job fails), then `scripts/k8s/smoke.sh http://<DEPLOY_HOST>` (website, health, `/api/models`, replay days, and checks
that `/api/metrics` is not public). The public URL is then **http://<DEPLOY_HOST>/**.

## 5. Prove rollback once (after the first deploy)
On the server (`ssh deploy@<DEPLOY_HOST>`):
```
kubectl -n flare set image deploy/api api=ghcr.io/veenaphadtare12-ux/flare-api:does-not-exist
kubectl -n flare rollout status deploy/api --timeout=60s     # fails: the new pod never becomes ready
curl -s http://localhost/api/health                            # still answers: old pods keep serving
kubectl -n flare rollout undo deploy/api && kubectl -n flare rollout status deploy/api
```
The same sequence runs automatically in the CI `kind` job on every push (`scripts/k8s/rollout_demo.sh`).

## 6. HTTPS with a domain
k3s serves the site through its Traefik ingress on port 80. For a certificate, add cert-manager and a TLS block to
`k8s/overlays/prod/ingress.yaml`, or run the Docker Compose stack on the server instead of k3s with
`SITE_ADDRESS=your.domain` in `.env` (Caddy gets and renews the Let's Encrypt certificate itself).

## Dry run already done (2026-11-14, local)
- The remote script CD generates was built with dummy secrets containing quotes and spaces: syntax OK, values arrive
  unchanged, and they travel on stdin, never as command-line arguments.
- The deploy bundle contains the prod overlay, `deploy.sh`, the Alertmanager entrypoint and the alert rules.
- `scripts/k8s/smoke.sh http://localhost` (the exact public smoke test) passed against the local stack through Caddy.
- `deploy.sh` and the prod overlay are exercised on a real cluster by the CI `kind` job on every push.
