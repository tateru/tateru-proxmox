# Tateru manager for Proxmox

proxmox intergation for Tateru deployment system

## Setup

Install dependencies
```bash
pip3 install -r requirements.txt
```

Update config file with your proxmox credentials, you only need to add one server per cluster as all servers have access to all other servers data.

After that you can just start the api
```bash
python3 manager.py
```
