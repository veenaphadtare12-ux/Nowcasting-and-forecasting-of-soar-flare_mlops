# Deployment on AWS (live)

**Status (2026-11-16): deployed.** Public URL: **https://veena-flare.duckdns.org** (Let's Encrypt certificate obtained
by Caddy). Everything below records how it was done and how to repeat or operate it.

| Item | Value |
|---|---|
| Cloud | AWS, free plan account ($120 credit, expires 2027-05-14) |
| Server | EC2 `m7i-flex.large` (2 vCPU, 8 GB RAM), Ubuntu 24.04, 30 GB gp3, region **ap-southeast-2 (Sydney)** |
| Address | Elastic IP 54.79.250.93; DuckDNS `veena-flare.duckdns.org` → that IP |
| Firewall | security group: SSH 22, HTTP 80, HTTPS 443 |
| Runtime | the same Docker Compose stack as locally (9 services), Caddy as the only public entry |
| Deploy | GitHub Actions CD → GHCR images → SSH → `scripts/deploy/server_deploy.sh <git sha>` → public HTTPS smoke test |
| Rollback | automatic: an unhealthy release, or a failed public smoke test, switches back to the previous image tag |
| Cost | about USD 0.12 per hour (~USD 87/month if never stopped) + disk and IP, paid from the credit |

## Why EC2 was created in the console and not with Terraform
The account is on AWS's new **free plan**, whose AWS-managed organisation applies a service control policy that denies
EC2 and Lightsail API calls made with IAM access keys (`explicit deny in a service control policy`, checked in four regions
on 2026-11-16). The console login is allowed, so the server was launched once by hand; CD itself needs no AWS
credentials at all, only SSH. The Terraform in `infra/terraform` (EC2) and `infra/lightsail` (Lightsail) describes the
same server as code and is validated in CI, but cannot be applied from this account.

## How it was set up (repeatable)
1. **SSH deploy key** (on the PC, in WSL): `ssh-keygen -t ed25519 -f ~/.ssh/flare_deploy -N "" -C flare-github-deploy`.
   EC2 → Key Pairs → Import key pair `flare-deploy` (the `.pub` line).
2. **Launch instance** (console, one region): Ubuntu 24.04 x86, `m7i-flex.large`, key pair `flare-deploy`, security group
   with SSH/HTTP/HTTPS from anywhere, 30 GB gp3, User data = `infra/lightsail/launch.sh` (installs Docker + Compose,
   2 GB swap, `/opt/flare`).
3. **Elastic IP**: allocate, associate with the instance.
4. **DuckDNS**: set the name's IP to the Elastic IP (one time; the Elastic IP does not change).
5. **GitHub secrets** (one command, values never printed):
   `.\scripts\deploy\set_github_secrets.ps1 -DeployHost <elastic ip>` → DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY,
   SITE_ADDRESS, ACME_EMAIL, FLARE_API_KEYS, GRAFANA_ADMIN_PASSWORD, SMTP_SMARTHOST, SMTP_USERNAME, SMTP_FROM,
   ALERT_EMAIL_TO, SMTP_PASSWORD (Gmail App Password, not the account password).
6. **Deploy**: `gh workflow run CD --ref master` (also runs automatically after every green CI run on master).

## Problems met
- The access key first pasted into a chat was replaced at once (never use a key that was shared).
- EC2/Lightsail API calls denied by the free plan's SCP → console launch (above).
- The instance was launched in Sydney because the console region was still set there (works; Mumbai would be cheaper).
- The HTTP/HTTPS rules were not saved at launch, so Let's Encrypt could not reach port 80; after adding them,
  `docker compose restart caddy` made Caddy retry and the certificate was issued within seconds.

## Save credit: stop the server between demos
Stopping keeps the disk, the Elastic IP and every volume; only disk and IP are billed (~USD 7/month).
- Console: EC2 → Instances → `flare` → **Instance state → Stop** / **Start**.
- After **Start**, wait ~2 minutes: Docker starts the stack by itself (`restart: unless-stopped`); check
  https://veena-flare.duckdns.org. If not, run CD once (`gh workflow run CD --ref master`).

## Operate
```
ssh -i ~/.ssh/flare_deploy ubuntu@54.79.250.93          # from WSL
cd /opt/flare && docker compose ps                        # status
bash scripts/deploy/server_deploy.sh --rollback           # back to the previous release
docker compose logs --tail 50 api                         # logs
```
Grafana, Prometheus, Prefect, MLflow and Alertmanager are bound to 127.0.0.1 on the server; open them through an SSH tunnel,
e.g. `ssh -i ~/.ssh/flare_deploy -L 3000:127.0.0.1:3000 ubuntu@54.79.250.93` then http://localhost:3000.

## Delete everything (when the project is over)
EC2 → Instances → `flare` → Terminate; Elastic IPs → Release; Security groups / Key pairs → delete; DuckDNS → change or
delete the name; GitHub → delete the DEPLOY_* and SMTP_* secrets; Google → revoke the App Password.
