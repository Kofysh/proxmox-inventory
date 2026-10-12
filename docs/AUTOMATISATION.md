# Collecte quotidienne avec systemd

Les fichiers `deploy/` fournissent un service à exécution unique, un timer quotidien et un adaptateur pour lire le secret transmis par systemd. Ils ciblent un hôte Linux avec systemd 247 ou supérieur et Python 3.10 ou supérieur.

## Comportement

- Collecte chaque jour à **04:00 Europe/Paris**, avec un décalage aléatoire de zéro à cinq minutes.
- Rattrapage d’une échéance manquée lorsque le timer est réactivé (`Persistent=true`).
- Compte dynamique `proxmox-inventory`, sans session interactive ni privilèges administrateur.
- Inventaires et comparaisons sous `/var/lib/proxmox-inventory/history`, conservés entre les exécutions.
- Répertoire de données privé ; système en lecture seule pour le service, sauf les emplacements gérés par systemd.
- Secret transmis par `LoadCredential`, absent de l’unité et de la ligne de commande. L’adaptateur le place en mémoire dans l’environnement du processus Python pendant la collecte.
- Encodage UTF-8 explicite pour conserver les accents dans les journaux.
- Une ligne de succès ou un message d’erreur dans le journal. Les inventaires détaillés ne sont pas écrits dans les journaux.

Le timer ne purge pas les rapports et ne renouvelle pas les jetons. L’utilisateur Proxmox et son jeton doivent tous deux rester actifs ; suivre leurs dates d’expiration.

## Installation

Depuis la racine du dépôt, avec les droits d’administration du serveur :

```bash
sudo install -d -m 755 /opt/proxmox-inventory /etc/proxmox-inventory
sudo install -m 644 proxmox_inventory.py deploy/scheduled_inventory.py /opt/proxmox-inventory/
sudo install -m 644 deploy/proxmox-inventory.service deploy/proxmox-inventory.timer /etc/systemd/system/
sudo install -m 600 deploy/pve.env.example /etc/proxmox-inventory/pve.env
```

Ces commandes remplacent les fichiers indiqués : conserver une copie de sa configuration avant toute réinstallation. Modifier `pve.env` avec l’URL accessible depuis le serveur, l’identifiant du jeton et le chemin du certificat. Ce fichier ne contient pas le secret. Le jeton et son utilisateur doivent avoir les ACL de lecture décrites dans [Installation](INSTALLATION.md).

Si une autorité interne est nécessaire, copier son certificat public dans `/etc/proxmox-inventory/ca.pem`, lisible par le compte du service (mode 644). Si l’autorité est reconnue par le système, retirer `PVE_CA_FILE` du fichier de configuration. Ne jamais désactiver la vérification TLS.

Enregistrer le secret dans `/etc/proxmox-inventory/token`, propriétaire `root:root`, mode `600`, au moyen d’un éditeur ou d’un gestionnaire de secrets. Ne pas le mettre dans Git, dans l’unité ou dans une commande enregistrée par l’historique. Le fichier est stocké en clair sur disque avec ces permissions ; `LoadCredential` fournit une copie privée au service pendant son exécution.

## Vérifier puis activer

```bash
sudo systemd-analyze verify /etc/systemd/system/proxmox-inventory.service /etc/systemd/system/proxmox-inventory.timer
sudo systemctl daemon-reload
sudo systemctl start proxmox-inventory.service
sudo journalctl -u proxmox-inventory.service -n 20 --no-pager
sudo systemctl enable --now proxmox-inventory.timer
systemctl list-timers proxmox-inventory.timer
```

Le service est de type `oneshot` : il redevient inactif après une collecte réussie. Vérifier `Result=success` et `ExecMainStatus=0`, plutôt que d’attendre un service en fonctionnement continu :

```bash
systemctl show proxmox-inventory.service -p Result -p ExecMainStatus
```

Un jeton expiré ou des droits insuffisants font échouer la collecte sans remplacer l’historique existant. Le timer tentera à nouveau à la prochaine échéance ; aucune alerte par e-mail n’est configurée.

## Désactiver ou ajuster

```bash
sudo systemctl disable --now proxmox-inventory.timer
```

Cette commande arrête la planification sans supprimer les rapports et sans interrompre une éventuelle collecte déjà lancée. Pour changer l’horaire, utiliser `systemctl edit proxmox-inventory.timer` avec un remplacement explicite :

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 06:00:00 Europe/Paris
```

Recharger les unités puis redémarrer le timer. Pour mettre le programme à jour, remplacer les deux fichiers Python dans `/opt/proxmox-inventory` depuis une version vérifiée, entre deux collectes.

## Références

- [Exécution, comptes dynamiques et credentials systemd](https://manpages.debian.org/trixie/systemd/systemd.exec.5.en.html)
- [Timers systemd](https://manpages.debian.org/trixie/systemd/systemd.timer.5.en.html)
