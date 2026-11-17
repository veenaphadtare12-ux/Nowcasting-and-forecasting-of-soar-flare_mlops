"""Deployment configuration guards (no Docker needed).

The official Prefect 3.8.7 image ships SQLAlchemy 2.1, which breaks Prefect's scheduler: on the AWS server the nightly
deployments never created a single run (found 2026-11-16). These tests keep the fix in place everywhere Prefect runs.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/veenaphadtare12-ux/flare-prefect-server"


def test_prefect_server_image_pins_sqlalchemy_2_0():
    df = (ROOT / "docker" / "prefect-server.Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM prefecthq/prefect:3\.8\.7-python3\.12$", df, re.M)
    pin = re.search(r"sqlalchemy==(\d+)\.(\d+)\.(\d+)", df)
    assert pin and (pin.group(1), pin.group(2)) == ("2", "0"), "SQLAlchemy must stay on the 2.0 line for Prefect 3.8.7"


def test_compose_and_kubernetes_use_the_patched_prefect_server():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = compose["services"]["prefect-server"]
    assert svc["image"].startswith(IMAGE + ":")
    assert svc["build"]["dockerfile"] == "docker/prefect-server.Dockerfile"
    k8s = (ROOT / "k8s" / "base" / "prefect.yaml").read_text(encoding="utf-8")
    assert f"image: {IMAGE}" in k8s and "prefecthq/prefect" not in k8s


def test_every_deploy_path_builds_and_ships_the_prefect_image():
    for f, needle in [
        (".github/workflows/cd.yml", "flare-prefect-server"),
        (".github/workflows/ci.yml", "build api frontend prefect-server"),
        ("scripts/deploy/server_deploy.sh", "pull --quiet api frontend prefect-server"),
        ("scripts/e2e.sh", "build api frontend prefect-server"),
        ("scripts/up.ps1", "build api frontend prefect-server"),
        ("scripts/newest_local_tag.sh", "flare-prefect-server"),
        ("scripts/k8s/kind_up.sh", "flare-prefect-server:$TAG"),
        ("scripts/k8s/deploy.sh", "flare-prefect-server"),
    ]:
        assert needle in (ROOT / f).read_text(encoding="utf-8"), f"{f} does not handle the Prefect server image"


def test_nginx_re_resolves_the_api_address():
    """nginx must look the API up again (resolver + variable), not once at start: recreating only the API container
    (new IP) made every /api request fail with 502 until the frontend was restarted (found 2026-11-17)."""
    tpl = (ROOT / "docker" / "nginx.conf.template").read_text(encoding="utf-8")
    assert "resolver ${NGINX_LOCAL_RESOLVERS} valid=10s" in tpl
    assert "set $api_upstream http://${API_HOST}:8000;" in tpl
    assert "proxy_pass http://api" not in tpl and tpl.count("proxy_pass $api_upstream;") == 2
    df = (ROOT / "docker" / "frontend.Dockerfile").read_text(encoding="utf-8")
    assert "/etc/nginx/templates/default.conf.template" in df and "NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1" in df
    k8s = (ROOT / "k8s" / "base" / "frontend.yaml").read_text(encoding="utf-8")
    assert "api.flare.svc.cluster.local" in k8s
