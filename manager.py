from flask import Flask, jsonify, request, abort, Response
from proxmoxer import ProxmoxAPI
import yaml

app = Flask(__name__)
app_config = None

def proxmox_connector(server, config):
	return ProxmoxAPI(server, user=config['username'],
                      password=config['password'], verify_ssl=False)


def inventories(config, connector=proxmox_connector):
	data = []

	for server in config['manager']:
		data.extend(get_inventory(connector(server, config)))

	return data


def get_inventory(proxmox):
	data = []
	for node in proxmox.nodes.get():
		for vm in proxmox.nodes(node['node']).get('qemu'):
			config = proxmox.nodes(node['node']).qemu(vm['vmid']).config().get()
			_, uuid = config['smbios1'].split('=')
			data.append({'uuid': uuid, 'name': vm['name']})

	return data


@app.route('/api/v1/machines', methods=['GET'])
def api_v1_machines():
	return jsonify(inventories(app_config))


if __name__ == '__main__':
	with open('config.yml') as f:
		app_config = yaml.load(f, Loader=yaml.FullLoader)

	app.run(**app_config['flask'])