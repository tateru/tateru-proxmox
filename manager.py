from flask import jsonify, Flask, Response
from logging import getLogger
from os import getenv
from proxmoxer import ProxmoxAPI
from yaml import safe_load

app = Flask(__name__)
app_config = None

# uuid: nonce mapping
installOperations: dict[str, str] = {}

logger = getLogger("proxmox-manager")


class ManagerException(Exception):
    pass


def get_setting(config, envvar, config_key, datatype=str, required=True, default=None):
    """
    Fetch a config parameter. Search order:

        Environment variable > Config dict (config_key) > default
    """
    value = getenv(envvar, None)

    if value is not None:
        if isinstance(value, datatype):
            return value
        else:
            if datatype == list:
                return value.split()  # split on whitespace
            elif datatype == bool:
                return value.lower() in ["true", "t", "1", "yes"]

            raise ManagerException(f"Unable to cast value for {envvar} to {datatype}")

    try:
        value = config[config_key]
        if isinstance(value, datatype):
            return value
        else:
            # No casting for config dict
            raise ManagerException(
                f"Invalid value for {config_key} in config file: should be {datatype} but is {type(value)}"
            )
    except KeyError:
        if required:
            raise ManagerException(
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
            logger.warning(f"Proxmox node {node} is unusable: {e}")

    raise ManagerException("No usable proxmox nodes found")


def extract_vm_uuid(vm_config):
    if not "smbios1" in vm_config:
        raise ManagerException("VM config has no UUID set (no smbios1 key)")

    options = vm_config.get("smbios1", "=").split(",")
    for option in options:
        parts = option.split("=", 1)

        if parts[0] == "uuid":
            if len(parts) != 2:
                raise ManagerException(
                    "VM config has no UUID set (cannot parse UUID key)"
                )
            else:
                # TODO: validate that this is actually a UUID?
                return parts[1]

    raise ManagerException("VM config has not UUID set (no UUID found)")


def inventory(config, connector=proxmox_connector):
    data = get_inventory(connector(config["manager"]))

    return data


def get_inventory(proxmox):
    """
    Collect basic data from each VM
    """
    data = []
    for node in proxmox.nodes.get():
        if node["status"] != "online":
            logger.warning(
                f"Unusable proxmox host {node['node']} in state {node['status']}"
            )
            continue

        vms = []
        try:
            vms = proxmox.nodes(node["node"]).get("qemu")
        except Exception as e:
            logger.warning(f"Proxmox node {node} is unusable: {e}")
            continue

        for vm in vms:
            config = None
            try:
                config = proxmox.nodes(node["node"]).qemu(vm["vmid"]).config().get()
            except Exception as e:
                logger.warning(
                    f"Unable to fetch QEMU VM configuration for {vm['vmid']} on node {node['node']}: {e}"
                )
                continue

            try:
                uuid = extract_vm_uuid(config)
            except ManagerException as e:
                logger.warning(
                    f"Unable to extract UUID for VM {vm['vmid']} on node {node['node']}: {e}"
                )
                continue

            data.append(
                {
                    "name": vm["name"],
                    "node": node["node"],
                    "uuid": uuid,
                    "vmid": vm["vmid"],
                }
            )

    return data


def get_vm(proxmox, uuid):
    """
    We need to somehow iterate all VMs, as we need the VM config to get the UUID,
    lets reuse the get_inventory() method
    """
    vms = get_inventory(proxmox)

    for vm in vms:
        if vm["uuid"] == uuid:
            return vm

    return None


def virtual_machine(config, uuid, connector=proxmox_connector):
    c = connector(config["manager"])
    vm = get_vm(c, uuid)
    if vm is not None:
        vm["_proxmox_connector"] = c
        return vm

    return None


@app.route("/v1/machines", methods=["GET"])
def api_v1_machines():
    data = [{"uuid": vm["uuid"], "name": vm["name"]} for vm in inventory(app_config)]

    return jsonify(data)


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
    vm_config = None
    try:
        vm_config = vm.config.get()
    except Exception:
        logger.exception(f"Unable to get VM config for VM {vm_data['vmid']}")
        raise

    nics = []
    for attr in vm_config:
        if attr.startswith("net"):
            nics.append(attr)

    # Set boot order to force network boot
    try:
        vm.config.put(boot=f"order={';'.join(nics)}")
    except Exception:
        logger.exception(f"Unable to update boot order for VM {vm_data['vmid']}")
        raise

    # Power off VM
    try:
        vm.status.stop.post()
    except Exception:
        logger.exception(f"Unable to stop VM {vm_data['vmid']}")
        raise

    # Power on VM
    try:
        vm.status.start.post()
    except Exception:
        logger.exception(f"Unable to start VM {vm_data['vmid']}")
        raise

    # Set default boot order (boot from disk)
    try:
        vm.config.put(boot="order=scsi0")
    except Exception:
        logger.exception(f"Unable to restore boot order for VM {vm_data['vmid']}")
        raise

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
    try:
        vm.status.stop.post()
    except Exception:
        logger.exception(f"Unable to stop VM {vm_data['vmid']}")
        raise

    # Power on VM
    try:
        vm.status.start.post()
    except Exception:
        logger.exception(f"Unable to stop VM {vm_data['vmid']}")
        raise

    return Response(status=200)


if __name__ == "__main__":
    with open("config.yml") as f:
        app_config = safe_load(f)

    app.run(**app_config["flask"])
