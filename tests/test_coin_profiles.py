"""Offline staging must not turn profile metadata into running coin services."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coins.py"
spec = importlib.util.spec_from_file_location("coin_staging", SCRIPT)
coins = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(coins)


@pytest.fixture
def registry():
    return coins.load_registry(ROOT / "config" / "coins.example.json")


def test_plans_are_isolated_and_never_create_chain_or_ledger(registry, tmp_path):
    storage = tmp_path / "selected-drive"
    plan = coins.build_plan(registry, storage)
    assert not storage.exists()
    assert plan["mode"] == "test-only"
    assert plan["starts_processes"] is plan["downloads_data"] is plan["payouts_enabled"] is False
    assert plan["storage_confirmed"] is False
    profiles = plan["profiles"]
    assert {p["coin"] for p in profiles} == {"btcs", "btc", "bch", "ltc", "doge"}
    paths = [p[key] for p in profiles for key in ("node_datadir", "pool_database")]
    assert len(set(paths)) == len(paths)
    ports = [port for p in profiles for port in p["ports"].values()]
    assert len(set(ports)) == len(ports)
    assert not ({3333, 8765, 18443, 18444} & set(ports))
    for profile in profiles:
        assert Path(profile["node_datadir"]).relative_to(storage) == Path("nodes") / profile["coin"] / "regtest"
        assert Path(profile["pool_database"]).relative_to(storage) == Path("pools") / profile["coin"] / "regtest" / "pool.sqlite3"
        assert all(value is False for value in profile["capabilities"].values())
        assert profile["pool_config"]["enabled"] is False
        assert profile["pool_config"]["auto_payouts"] is False
        assert profile["node_runtime_verified"] is profile["pool_integration_verified"] is False
        assert profile["identity_expectation"]["chain"] == "regtest"
        assert profile["identity_expectation"]["verified"] is False
        assert profile["identity_expectation"]["requires_reviewed_pinned_binary"] is True
    assert [p["coin"] for p in profiles if p["backend_adapter_available"]] == ["btcs"]
    assert [p["coin"] for p in profiles if p["pool_adapter"]] == ["btcs"]


def test_generated_configs_use_local_regtest_and_cookie_auth(registry, tmp_path):
    for profile in coins.build_plan(registry, tmp_path / "drive")["profiles"]:
        config = profile["node_config"]
        lines = set(config.splitlines())
        assert {"regtest=1", "[regtest]", "rpcbind=127.0.0.1", "rpcallowip=127.0.0.1",
                "listen=0", "discover=0", "dnsseed=0", "connect=0", "server=1",
                "prune=0", "txindex=0"} <= lines
        assert f"rpcport={profile['ports']['rpc']}" in lines
        assert f"port={profile['ports']['p2p']}" in lines
        assert "rpcpassword=" not in config and "rpcuser=" not in config
        assert "0.0.0.0" not in config and "mainnet" not in config
        assert profile["rpc_url"].startswith("http://127.0.0.1:")


@pytest.mark.parametrize("flag", sorted(coins.DISABLED_FLAGS))
@pytest.mark.parametrize("unsafe_value", [True, 1, "false", None])
def test_execution_flags_cannot_be_enabled(registry, flag, unsafe_value):
    registry["coins"][0][flag] = unsafe_value
    with pytest.raises(coins.ProfileError, match="must remain false"):
        coins.validate_registry(registry)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(mode="mainnet"),
    lambda r: r.update(schema_version=True),
    lambda r: r.update(launch=True),
    lambda r: r["coins"][0].update(rpcbind="0.0.0.0"),
    lambda r: r["coins"][0].update(id="../btc"),
    lambda r: r["coins"][0].update(id="unreviewed"),
    lambda r: r["coins"][0].update(config_filename="../bitcoin.conf"),
    lambda r: r["coins"][0].update(daemon="bitcoind; start"),
    lambda r: r["coins"][1].update(pool_adapter="existing-btcs-sha256d"),
    lambda r: r["coins"][3].update(algorithm="sha256d"),
    lambda r: r["coins"].append(copy.deepcopy(r["coins"][0])),
    lambda r: r["coins"][0]["regtest"].update(expected_genesis_hash=""),
    lambda r: r["coins"][0].update(source_url="https://user:secret@example.com/source"),
])
def test_unknown_or_unsafe_registry_inputs_fail_closed(registry, mutation):
    mutation(registry)
    with pytest.raises(coins.ProfileError):
        coins.validate_registry(registry)


@pytest.mark.parametrize("port", [True, "20443", 0, 80, 65536])
def test_invalid_ports_are_rejected(registry, port):
    registry["coins"][1]["regtest"]["ports"]["rpc"] = port
    with pytest.raises(coins.ProfileError, match="port"):
        coins.validate_registry(registry)


def test_port_collision_rejected_even_for_unselected_profile(registry, tmp_path):
    registry["coins"][1]["regtest"]["ports"]["rpc"] = registry["coins"][0]["regtest"]["ports"]["api"]
    with pytest.raises(coins.ProfileError, match="port collision"):
        coins.build_plan(registry, tmp_path / "drive", ["btcs"])


@pytest.mark.parametrize("selection", [["unknown"], ["btc", "btc"], []])
def test_unknown_or_duplicate_coin_selection_is_rejected(registry, tmp_path, selection):
    with pytest.raises(coins.ProfileError):
        coins.build_plan(registry, tmp_path / "drive", selection)


@pytest.mark.parametrize("network", ["main", "mainnet", "test", "signet", ""])
def test_only_regtest_plans_are_allowed(registry, tmp_path, network):
    with pytest.raises(coins.ProfileError, match="only isolated regtest"):
        coins.build_plan(registry, tmp_path / "drive", network=network)


@pytest.mark.parametrize("path", ["relative/drive", "/", "/tmp/a/../drive", "/tmp/drive\nrpcbind=0.0.0.0", "/tmp/drive#comment"])
def test_unsafe_storage_paths_are_rejected(registry, path):
    with pytest.raises(coins.ProfileError):
        coins.build_plan(registry, path)


def test_existing_node_or_ledger_and_symlink_paths_are_rejected(registry, tmp_path):
    storage = tmp_path / "drive"
    node = storage / "nodes" / "btc" / "regtest"
    node.mkdir(parents=True)
    with pytest.raises(coins.ProfileError, match="existing node data"):
        coins.build_plan(registry, storage, ["btc"])
    node.rmdir()
    ledger = storage / "pools" / "btc" / "regtest" / "pool.sqlite3"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("existing ledger")
    with pytest.raises(coins.ProfileError, match="pool database"):
        coins.build_plan(registry, storage, ["btc"])
    ledger.unlink()
    alias = tmp_path / "drive-alias"
    alias.symlink_to(storage, target_is_directory=True)
    with pytest.raises(coins.ProfileError, match="symlink"):
        coins.build_plan(registry, alias, ["btc"])


def test_bundle_contains_only_private_review_files_and_refuses_overwrite(registry, tmp_path):
    storage = tmp_path / "drive"
    plan = coins.build_plan(registry, storage, ["btc", "ltc"])
    output = tmp_path / "review"
    artifact = coins.write_bundle(plan, output)
    assert artifact == output / "plan.json"
    assert {p.name for p in output.iterdir()} == {"plan.json", "btc-regtest.conf", "ltc-regtest.conf"}
    assert json.loads(artifact.read_text()) == plan
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir())
    assert not storage.exists()
    with pytest.raises(coins.ProfileError, match="overwrite"):
        coins.write_bundle(plan, output)
    assert json.loads(artifact.read_text()) == plan
    with pytest.raises(coins.ProfileError, match="outside the planned"):
        coins.write_bundle(plan, Path(plan["profiles"][0]["node_datadir"]))
    with pytest.raises(coins.ProfileError, match="outside the planned"):
        coins.write_bundle(plan, storage / "review")
    assert not storage.exists()


def test_bundle_rejects_symlink_output(registry, tmp_path):
    destination = tmp_path / "other"
    destination.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(destination, target_is_directory=True)
    plan = coins.build_plan(registry, tmp_path / "drive", ["btc"])
    with pytest.raises(coins.ProfileError, match="symlink"):
        coins.write_bundle(plan, alias)
    assert list(destination.iterdir()) == []


def test_duplicate_json_keys_do_not_silently_override_safety(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text('{"schema_version":1,"mode":"mainnet","mode":"test-only","coins":[]}')
    with pytest.raises(coins.ProfileError, match="duplicate JSON key"):
        coins.load_registry(registry)


def test_cli_validate_and_plan_are_offline_without_side_effects(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "validate"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ready_to_start"] is False
    storage = tmp_path / "not-created"
    result = subprocess.run([sys.executable, str(SCRIPT), "plan", "--coin", "doge",
                             "--storage-root", str(storage)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["profiles"][0]["pool_adapter"] is None
    assert not storage.exists()


def test_planning_does_not_launch_processes_or_contact_network(monkeypatch, tmp_path, capsys):
    import socket
    import urllib.request

    def forbidden(*args, **kwargs):
        pytest.fail("offline staging must never start a process or use the network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    storage, output = tmp_path / "drive", tmp_path / "review"
    assert coins.main(["plan", "--coin", "btc", "--storage-root", str(storage),
                       "--write-dir", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["starts_processes"] is False
    assert not storage.exists()
    assert (output / "plan.json").is_file()


@pytest.mark.parametrize("arguments", [
    ["start"], ["download"], ["mine"], ["payout"],
    ["plan", "--network", "main", "--storage-root", "/tmp/coin-tests"],
    ["plan", "--coin", "unknown", "--storage-root", "/tmp/coin-tests"],
    ["plan", "--storage-root", "/tmp/coin-tests", "--enable-payouts"],
])
def test_cli_has_no_mainnet_or_execution_escape_hatch(arguments):
    result = subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True)
    assert result.returncode == 2
    assert result.stdout == ""


def test_shared_genesis_is_not_reported_as_verified_coin_identity(registry, tmp_path):
    profiles = coins.build_plan(registry, tmp_path / "drive", ["btc", "bch", "btcs"])["profiles"]
    assert len({p["identity_expectation"]["genesis_hash"] for p in profiles}) == 1
    assert all(not p["identity_expectation"]["verified"] for p in profiles)
    assert all("not unique across forks" in p["identity_expectation"]["note"] for p in profiles)
