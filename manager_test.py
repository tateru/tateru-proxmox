import unittest
from unittest.mock import MagicMock

import manager


nodes = [
    {
        "maxdisk": 24743342080,
        "cpu": 0.0904872112454131,
        "mem": 155738619904,
        "level": "",
        "node": "node1",
        "status": "online",
        "ssl_fingerprint": "DC:F9:52:53:EF:EF:92:83:E6:86:97:D0:91:93:90:D9:6B:97:07:25:A9:0D:A1:28:0F:25:15:8C:FE:99:A2:05",
        "maxcpu": 40,
        "disk": 4235063296,
        "uptime": 4195739,
        "maxmem": 201420058624,
        "type": "node",
        "id": "node/node1",
    }
]

qemu = {
    "node1": [
        {
            "vmid": "1",
            "pid": "5130",
            "netout": 44539988293,
            "mem": 1734115988,
            "template": "",
            "cpu": 0.0475956802379353,
            "netin": 47976268606,
            "disk": 0,
            "diskread": 0,
            "status": "running",
            "name": "vm1.fqdn",
            "uptime": 1806468,
            "diskwrite": 0,
            "maxdisk": 34359738368,
            "cpus": 1,
            "maxmem": 2147483648,
        }
    ]
}

qemu_config = {
    "node1": {
        "1": {  # vm1.fqdn
            "memory": 4096,
            "scsi0": "storage3:1/vm-1-disk-0.qcow2,size=32G",
            "vmgenid": "89e60754-6cf3-4b77-a075-229d25a43101",
            "cores": 2,
            "digest": "e7506848024e2400f29fe76f28cd65b4bb9c38fd",
            "name": "",
            "boot": "order=scsi0;net0",
            "net0": "vmxnet3=00:00:00:00:00:01,bridge=vmbr0",
            "smbios1": "uuid=eaa1f69d-efab-46f4-8ae7-a8d1658845fa",
        }
    }
}


class TestManager(unittest.TestCase):
    def setUp(self):
        self.config = {"manager": {"proxmox.local": {}}}

        def node1_get(key):
            if key != "qemu":
                raise Exception("node_get only supports qemu key")
            return qemu["node1"]

        self.proxmox_mock = MagicMock()
        self.proxmox_mock.nodes.get.return_value = nodes
        self.proxmox_mock.nodes("node1").get = MagicMock(side_effect=node1_get)
        self.proxmox_mock.nodes("node1").qemu(
            "1"
        ).config().get.return_value = qemu_config["node1"]["1"]

    def proxmox_connector(self, config):
        return self.proxmox_mock

    def test_inventory(self):
        got = manager.inventory(self.config, connector=self.proxmox_connector)
        expected = [
            {"uuid": "eaa1f69d-efab-46f4-8ae7-a8d1658845fa", "name": "vm1.fqdn"}
        ]
        self.assertEqual(expected, got)

    def test_virtual_machine(self):
        got = manager.virtual_machine(
            self.config,
            "eaa1f69d-efab-46f4-8ae7-a8d1658845fa",
            connector=self.proxmox_connector,
        )
        expected = {
            "uuid": "eaa1f69d-efab-46f4-8ae7-a8d1658845fa",
            "name": "vm1.fqdn",
        }
        self.assertEqual(expected, got)


if __name__ == "__main__":
    unittest.main()
