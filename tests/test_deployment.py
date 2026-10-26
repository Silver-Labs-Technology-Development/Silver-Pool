from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
PROD_COMPOSE = ROOT / "deploy" / "docker-compose.prod.yml"
ENV_EXAMPLE = ROOT / ".env.example"


def load_compose(path: Path) -> dict:
    class ComposeLoader(yaml.SafeLoader):
        pass

    def override(loader, node):
        return loader.construct_sequence(node)

    ComposeLoader.add_constructor("!override", override)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=ComposeLoader)


def test_compose_defines_node_pool_web_with_persistence_and_ordering():
    document = load_compose(COMPOSE)
    services = document["services"]
    assert set(services) == {"node", "pool", "web"}

    node = services["node"]
    pool = services["pool"]
    web = services["web"]

    assert node["volumes"] == ["node-data:/data"]
    assert pool["volumes"] == ["pool-data:/data"]
    assert "caddy-data:/data" in web["volumes"]
    assert {"node-data", "pool-data", "caddy-data", "caddy-config"} <= set(
        document["volumes"]
    )

    assert pool["depends_on"]["node"]["condition"] == "service_healthy"
    assert web["depends_on"]["pool"]["condition"] == "service_started"
    for service in (node, pool, web):
        assert service["restart"] == "unless-stopped"
        assert service["init"] is True
        assert service["logging"]["driver"] == "json-file"

    assert node["healthcheck"]["test"] == ["CMD", "/usr/local/bin/btcs-node-healthcheck"]
    assert node["security_opt"] == ["no-new-privileges:true"]
    assert pool["security_opt"] == ["no-new-privileges:true"]


def test_rpc_and_api_are_never_published_but_stratum_and_web_are():
    services = load_compose(COMPOSE)["services"]
    node_ports = services["node"].get("ports", [])
    pool_ports = services["pool"].get("ports", [])
    web_ports = services["web"].get("ports", [])

    assert node_ports == ["${BTCS_P2P_PORT:-10566}:${BTCS_P2P_PORT:-10566}"]
    assert not any("10567" in str(port) for port in node_ports)
    assert not any("18443" in str(port) for port in node_ports)
    assert pool_ports == ["${BTCS_STRATUM_PORT:-3333}:${BTCS_STRATUM_PORT:-3333}"]
    assert services["pool"]["expose"] == ["8765"]
    assert not any("8765" in str(port) for port in pool_ports)
    assert web_ports and all(":80" in str(port) for port in web_ports)
    assert services["pool"]["environment"]["BTCS_POOL_API_HOST"] == "0.0.0.0"
    assert services["pool"]["environment"]["BTCS_AUTO_PAYOUTS"] == "false"


def test_production_overlay_uses_caddy_tls_and_explicit_hostname():
    overlay = load_compose(PROD_COMPOSE)["services"]["web"]
    assert overlay["ports"] == ["80:80", "443:443", "443:443/udp"]
    assert "SILVER_POOL_SITE_ADDRESS" in overlay["environment"]
    assert ":?" in overlay["environment"]["SILVER_POOL_SITE_ADDRESS"]


def test_node_image_pins_official_release_and_checksum():
    compose = load_compose(COMPOSE)["services"]["node"]["build"]["args"]
    dockerfile = (ROOT / "deploy" / "node" / "Dockerfile").read_text(encoding="utf-8")
    assert "31.1.3" in compose["BTCS_VERSION"]
    assert "version31.1.3/bitcoinsilver-31.1.3-x86_64-linux-gnu.tar.gz" in compose[
        "BTCS_RELEASE_URL"
    ]
    sha = compose["BTCS_RELEASE_SHA256"]
    pinned = "6743ecef53501687574a5f761ddb41dcce960953e0e0b6ef362ab69268767c4c"
    assert pinned in sha
    assert pinned in dockerfile
    assert "sha256sum --check" in dockerfile
    assert "bitcoinsilverd" in dockerfile
    assert "bitcoinsilver-cli" in dockerfile


def test_pool_and_web_images_run_non_root_and_do_not_embed_secrets():
    pool = (ROOT / "deploy" / "pool" / "Dockerfile").read_text(encoding="utf-8")
    web = (ROOT / "deploy" / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER 10001:10001" in pool
    assert '"btcs_pool.server"' in pool
    assert "HEALTHCHECK" in pool
    assert "HEALTHCHECK" in web
    assert "npm ci" in web
    assert "npm run build" in web
    for text in (pool, web):
        assert "RPC_PASSWORD" not in text
        assert "BEGIN PRIVATE KEY" not in text


def test_caddy_proxies_api_and_serves_real_multipage_routes():
    caddyfile = (ROOT / "deploy" / "web" / "Caddyfile").read_text(encoding="utf-8")
    assert "reverse_proxy pool:8765" in caddyfile
    assert "root * /srv" in caddyfile
    assert "try_files {path} {path}/ /index.html" in caddyfile
    assert "/statistics /miners /miner /blocks" in caddyfile
    assert "Content-Security-Policy" in caddyfile
    assert "X-Frame-Options" in caddyfile
    assert "handle /healthz" in caddyfile


def test_env_example_is_placeholder_only_and_payouts_disabled():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    values = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    assert values["BTCS_AUTO_PAYOUTS"] == "false"
    assert values["BTCS_PUBLIC_STRATUM_HOST"] == ""
    assert values["BTCS_RPC_PASSWORD"].startswith("replace-with-")
    assert values["BTCS_POOL_ADDRESS"] == ""
    assert "stratum.silver-pool.example" not in text
    assert values["BTCS_TRUSTED_PROXIES"] == "172.16.0.0/12"
    assert values["SILVER_POOL_HTTP_BIND"] == "127.0.0.1"
    assert "BTCS_RELEASE_SHA256=6743ecef53501687574a5f761ddb41dcce960953e0e0b6ef362ab69268767c4c" in text


def test_dockerignore_excludes_secrets_chain_data_and_runtime_state():
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for pattern in (".env", "data", "*.sqlite3", "wallet.dat", "node_modules", "site/_site", "secrets"):
        assert pattern in text
