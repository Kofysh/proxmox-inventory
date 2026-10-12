#!/usr/bin/env python3
"""Adaptateur systemd : charger le secret sans le placer dans l’unité."""
import os
from pathlib import Path
import sys

from proxmox_inventory import main


def run():
    try:
        credential_dir = os.environ['CREDENTIALS_DIRECTORY']
        secret = (Path(credential_dir) / 'pve-token').read_text(encoding='utf-8').strip()
        if not secret:
            raise ValueError
    except (KeyError, OSError, UnicodeError, ValueError):
        print('ERREUR : credential systemd pve-token absent ou illisible.', file=sys.stderr)
        return 1
    os.environ['PVE_TOKEN_SECRET'] = secret
    try:
        code = main(['--history', '/var/lib/proxmox-inventory/history', '--quiet'])
    finally:
        os.environ.pop('PVE_TOKEN_SECRET', None)
    if code == 0:
        print('Collecte terminee : inventaire et historique enregistres.')
    return code


if __name__ == '__main__':
    sys.exit(run())
