import os
import requests
import yaml

from flask import Flask, jsonify, request, abort, Response
from proxmoxer import ProxmoxAPI

app = Flask(__name__)
app_config = None

# uuid: nonce mapping
installOperations = {}


def get_setting(config, envvar, config_key, datatype=str, required=True, default=None):
    """
    Fetch a config parameter. Search order:

        Environment variable > Config dict (config_key) > default
    """
    value = os.getenv(envvar, None)

    if value is not None:
        if isinstance(value, datatype):
            return value
        else:
            if datatype == list:
                return value.split()  # split on whitespace
            elif datatype == bool:
                return value.lower() in ["true", "t", "1", "yes"]

            raise Exception(f"Unable to cast value for {envvar} to {datatype}")

    try:
        value = config[config_key]
        if isinstance(value, datatype):
            return value
        else:
            # No casting for config dict
            raise Exception(
                f"Invalid value for {config_key} in config file: should be {datatype} but is {type(value)}"
            )
    except KeyError:
        if required:
            raise Exception(
                f"Missing configuration: {config_key} is required, specify either in the config file or as {envvar} environment variable"
            )
        else:
            return default


def proxmox_connector(config):
    nodes = get_setting(config, "PROXMOX_MANAGER_NODES", "nodes", datatype=list)

    for node in nodes:
        settings = {
            "user": get_setting(config, "PROXMOX_MANAGER_USERNAME", "username"),
            "password": get_setting(config, "PROXMOX_MANAGER_PASSWORD", "password"),
            "verify_ssl": get_setting(
                config,
                "PROXMOX_MANAGER_SSL_VERIFY",
                "ssl_verify",
                datatype=bool,
                required=False,
                default=True,
            ),
        }

        connector = ProxmoxAPI(
            node,
            **settings,
        )

        try:
            connector.version.get()

            return connector
        except Exception as e:
            print(f"Warning: Proxmox node {node} is unusable: {e}")

    raise Exception("No usable proxmox nodes found")


def extract_vm_uuid(vm_config):
    if not "smbios1" in vm_config:
        print(
            f"Warning: VM {vm['vmid']} on node {vm['node']} has no UUID set (no smbios1 key)"
        )

    options = vm_config.get("smbios1", "=").split(",")
    for option in options:
        parts = option.split("=", 1)

        if parts[0] == "uuid":
            if len(parts) != 2:
                print(
                    f"Warning: VM {vm['vmid']} on node {vm['node']} has no UUID set (cannot parse UUID key)"
                )
            else:
                return parts[1]

    print(
        f"Warning: VM {vm['vmid']} on node {vm['node']} has not UUID set (no UUID found)"
    )


def inventory(config, connector=proxmox_connector):
    data = get_inventory(connector(config["manager"]))

    return data


def get_inventory(proxmox):
    data = []
    for node in proxmox.nodes.get():
        for vm in proxmox.nodes(node["node"]).get("qemu"):
            config = proxmox.nodes(node["node"]).qemu(vm["vmid"]).config().get()
            uuid = extract_vm_uuid(config)
            data.append({"uuid": uuid, "name": vm["name"]})

    return data


def virtual_machine(config, uuid, connector=proxmox_connector):
    c = connector(config["manager"])
    vm = get_vm(c, uuid)
    if vm is not None:
        vm["_proxmox_connector"] = c
        return vm

    return None


def get_vm(proxmox, uuid):
    for vm in proxmox.cluster.resources.get(type="vm"):
        config = proxmox.nodes(vm["node"]).qemu(vm["vmid"]).config.get()
        vm_uuid = extract_vm_uuid(config)

        if uuid == vm_uuid:
            return vm

    return None


@app.route("/v1/machines", methods=["GET"])
def api_v1_machines():
    return jsonify(inventory(app_config))


@app.route("/v1/machines/<uuid:uuid>/boot-installer", methods=["POST"])
def api_v1_boot_installer(uuid):
    # According to the spec, there is a JSON payload in the request containing
    # nonce, but currently we have no use for it, so leave request body be.
    # TODO: add nonce from installOperations, fail/noop if there is another
    #       install request inflight for this uuid

    vm_data = virtual_machine(app_config, str(uuid))
    if vm_data is None:
        return Response(status=404)

    vm = vm_data["_proxmox_connector"].nodes(vm_data["node"]).qemu(vm_data["vmid"])

    # Get list of all nics
    nics = []
    for attr in vm.config.get():
        if attr.startswith("net"):
            nics.append(attr)

    # Set boot order to force network boot
    vm.config.put(boot=f"order={';'.join(nics)}")

    # Power off VM
    vm.status.stop.post()

    # Power on VM
    vm.status.start.post()

    # Set default boot order (boot from disk)
    vm.config.put(boot="order=scsi0")

    return Response(status=200)


@app.route("/v1/machines/<uuid:uuid>/exit-installer", methods=["POST"])
def api_v1_exit_installer(uuid):
    # According to the spec, there is a JSON payload in the request containing
    # nonce, but currently we have no use for it, so leave request body be.
    # TODO: remove nonce from installOperations, fail if there is no such installOperation

    vm_data = virtual_machine(app_config, str(uuid))
    if vm_data is None:
        return Response(status=404)

    vm = vm_data["_proxmox_connector"].nodes(vm_data["node"]).qemu(vm_data["vmid"])

    # Power off VM
    vm.status.stop.post()

    # Power on VM
    vm.status.start.post()

    return Response(status=200)


if __name__ == "__main__":
    with open("config.yml") as f:
        app_config = yaml.load(f, Loader=yaml.FullLoader)

    app.run(**app_config["flask"])
