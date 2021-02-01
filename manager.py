from flask import Flask, jsonify, request, abort, Response
from proxmoxer import ProxmoxAPI
import yaml

app = Flask(__name__)
	
def main():
	data = []

	for server in config['manager']:
		data.append(getInventory(server, config))

	return data


def getInventory(server, config):
	data = []
	proxmox = ProxmoxAPI(server, user=config['manager'][server]['username'],
                     password=config['manager'][server]['password'], verify_ssl=False)

	for node in proxmox.nodes.get():
		for vm in proxmox.nodes(node['node']).get('qemu'):
			config = proxmox.nodes(node['node']).qemu(vm['vmid']).config().get()
			_, uuid = config['smbios1'].split("=")
			data.append({"uuid": uuid, "name": vm['name']})

	return data


@app.route('/api/v1/machines', methods=['GET'])
def inventory():
	return jsonify(main())

if __name__ == '__main__':
	with open('config.yml') as f:
		config = yaml.load(f, Loader=yaml.FullLoader)

	app.run(debug=config['api']['debug'], port=config['api']['port'])

