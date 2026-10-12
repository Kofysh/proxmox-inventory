# Installation et configuration

Ce guide décrit la connexion à une infrastructure Proxmox réelle. Pour découvrir l’outil sans serveur, consulter le [démarrage rapide](../README.md#demarrage-rapide).

### 1. Créer les accès en lecture seule

Depuis l’interface d’administration Proxmox, avec un compte habilité :

1. Créer un utilisateur dédié, par exemple `inventory@pve`, dans **Datacenter → Permissions → Users**.
2. Attribuer le rôle **PVEAuditor** à cet utilisateur sur le chemin `/`, avec propagation, pour un inventaire de tout le cluster. Si le périmètre autorisé est plus restreint, adapter les ACL : le rapport sera alors partiel.
3. Créer un jeton API `b2-inventory` pour cet utilisateur en conservant la **séparation des privilèges** activée. Une expiration peut être définie selon la durée du projet.
4. Attribuer également au jeton le rôle **PVEAuditor** sur `/`, avec propagation, dans les permissions du jeton.
5. Conserver le secret affiché à la création dans un emplacement sûr. Il n’est pas inclus dans ce projet.

Avec la séparation des privilèges, les droits effectifs du jeton sont limités par ceux de l’utilisateur et par ses propres ACL. Une liste vide peut résulter de droits insuffisants même lorsque l’API répond HTTP 200. Vérifier les ressources visibles avec l’administrateur avant de conclure que l’inventaire est complet. Ne pas utiliser de jeton administrateur pour cet outil.

### 2. Préparer HTTPS et l’accès réseau

Exécuter depuis un poste ou serveur pouvant joindre l’API privée, généralement sur le port 8006, éventuellement via un VPN. Il n’est pas nécessaire de publier Proxmox sur Internet.

Le nom DNS utilisé doit correspondre au certificat. Si Proxmox utilise une autorité interne, récupérer **le certificat public de cette autorité**, par un canal d’administration de confiance, puis définir `PVE_CA_FILE` vers ce fichier PEM. Ne pas copier sa clé privée. Un certificat reconnu par le système ne nécessite pas cette variable. L’outil ne propose pas de désactivation de TLS.

### 3. Définir les variables

Le fichier `.env.example` décrit le format ; **il n’est pas chargé automatiquement**. Le script lit les variables d’environnement du processus.

| Variable | Obligatoire | Exemple / valeur par défaut |
|---|---|---|
| `PVE_URL` | Oui | `https://pve.example.net:8006`, sans `/api2/json` |
| `PVE_TOKEN_ID` | Oui | `inventory@pve!b2-inventory` |
| `PVE_TOKEN_SECRET` | Oui | Secret communiqué à la création du jeton |
| `PVE_CA_FILE` | Non | Chemin vers l’autorité de confiance PEM |
| `PVE_TIMEOUT` | Non | `10`, délai par opération réseau, maximum 120 s |

**Linux / Bash :**

```bash
export PVE_URL='https://pve.example.net:8006'
export PVE_TOKEN_ID='inventory@pve!b2-inventory'
read -r -s -p 'Secret du jeton : ' PVE_TOKEN_SECRET
export PVE_TOKEN_SECRET
printf '\n'
# Si autorité interne : adapter ce chemin.
export PVE_CA_FILE='/chemin/vers/pve-root-ca.pem'
python3 proxmox_inventory.py --output reports/inventory-live.json
unset PVE_TOKEN_SECRET
```

**Windows / PowerShell :**

```powershell
$env:PVE_URL = 'https://pve.example.net:8006'
$env:PVE_TOKEN_ID = 'inventory@pve!b2-inventory'
$secret = Read-Host 'Secret du jeton' -AsSecureString
$env:PVE_TOKEN_SECRET = [System.Net.NetworkCredential]::new('', $secret).Password
# Si autorité interne : adapter ce chemin.
$env:PVE_CA_FILE = 'C:\certificats\pve-root-ca.pem'
py -3 proxmox_inventory.py --output reports/inventory-live.json
Remove-Item Env:PVE_TOKEN_SECRET
Remove-Variable secret
```

Supprimer la ligne `PVE_CA_FILE` si elle n’est pas nécessaire. Les valeurs données sont des exemples et doivent être remplacées. La saisie du secret évite de le taper en clair dans l’historique des commandes ; il reste nécessairement présent dans la mémoire du processus et son environnement pendant l’exécution.

### 4. Lire les résultats

```bash
python3 proxmox_inventory.py --help
python3 proxmox_inventory.py --version
python3 proxmox_inventory.py --demo --output reports/demo.json
```

Un exemple complet est fourni dans `examples/report-demo.json` et son résumé dans `examples/console-demo.txt`.

- `mode` distingue les données fictives (`demo`) d’une collecte API (`live`).
- `collection_status: completed` signifie que les deux collectes ont abouti ; ce n’est pas un certificat de conformité ni une preuve d’exhaustivité.
- `summary` compte les nœuds, les invités actifs/arrêtés/autres et les modèles.
- `nodes` et `guests` contiennent les données normalisées ; les tailles sont en octets.
- `warnings` indique les limites de visibilité et les éventuels nœuds hors ligne.
- `disk_reported_bytes` reprend `maxdisk` de l’API. Ce champ n’est pas la somme garantie de tous les disques d’une VM, ni une mesure de l’espace réellement occupé.

Une VM arrêtée peut l’être volontairement : cela ne déclenche pas d’échec. L’état d’un nœud hors ligne est signalé sans empêcher l’export.

Le fichier de destination est remplacé atomiquement après une collecte réussie. **En cas d’échec, un ancien rapport peut rester présent** : vérifier le code de retour et `generated_at`. Ne pas confondre l’ancien résultat avec une nouvelle mesure.

| Code de sortie | Sens |
|---|---|
| `0` | Collecte ou comparaison réussie, même si des avertissements ou différences existent |
| `1` | Erreur de configuration, collecte ou écriture |
| `2` | Arguments de ligne de commande invalides |
| `130` | Interruption au clavier |

### Dépannage

| Message / symptôme | Vérification |
|---|---|
| HTTP 401 | Identifiant complet du jeton, secret, expiration, utilisateur actif |
| HTTP 403 | ACL de l’utilisateur et du jeton, propagation |
| Liste vide ou incomplète | Visibilité autorisée par les ACL ; comparer avec l’interface d’administration |
| Connexion impossible | VPN/routage, DNS, port 8006, délai, chaîne de confiance et nom du certificat |
| Redirection refusée | Utiliser directement l’origine HTTPS de l’API |
| JSON invalide | Vérifier que l’URL cible Proxmox et non une page de connexion de proxy |


## Références

- [API Proxmox VE](https://pve.proxmox.com/wiki/Proxmox_VE_API)
- [Gestion des utilisateurs et des permissions](https://pve.proxmox.com/pve-docs/pveum-plain.html)
- [Référence des routes API](https://pve.proxmox.com/pve-docs/api-viewer/index.html)

## Filtres et comparaison

```bash
python3 proxmox_inventory.py --node pve-lab-01 --status running
python3 proxmox_inventory.py --compare reports/avant.json reports/apres.json --output reports/ecarts.json
```

Les filtres concernent uniquement le terminal ; le JSON conserve l’inventaire complet. `--compare` est un mode hors ligne, incompatible avec `--demo`, `--node` et `--status`. L’ordre des fichiers est ancien puis nouveau. Le mode comparaison utilise `reports/comparison.json` comme destination par défaut.

Pour conserver plusieurs mesures réelles, choisir un nom distinct à chaque collecte avec `--output`. Les rapports doivent provenir de la même URL et du même périmètre d’accès ; le logiciel vérifie l’URL et le mode mais ne peut pas vérifier que les ACL sont restées identiques.
