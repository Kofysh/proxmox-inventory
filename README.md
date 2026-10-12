<div align="center">

# Proxmox Inventory

**L’inventaire d’une infrastructure Proxmox, depuis le terminal.**

Nœuds, machines virtuelles et conteneurs · Export JSON · Lecture seule

**Python 3.10+** &nbsp; / &nbsp; **Sans dépendance externe** &nbsp; / &nbsp; **Version 1.2.0**

[![Tests Python](https://github.com/Kofysh/proxmox-inventory/actions/workflows/tests.yml/badge.svg)](https://github.com/Kofysh/proxmox-inventory/actions/workflows/tests.yml)

[Démarrage rapide](#demarrage-rapide) · [Configuration](docs/INSTALLATION.md) · [Validation](docs/VALIDATION.md)

</div>

---

## Le projet

Proxmox Inventory rassemble les informations utiles d’un cluster dans un rapport horodaté : état des nœuds, machines virtuelles, conteneurs et ressources attribuées. Un résumé permet de consulter l’inventaire dans le terminal ; le fichier JSON peut être conservé ou réutilisé dans un autre outil.

Ce dépôt accompagne le **projet 1 de Bachelor 2 à OTERIA**, consacré à une plateforme d’hébergement VPS avec Proxmox et Paymenter. L’outil interroge directement Proxmox et fonctionne indépendamment du connecteur Paymenter.

| Inventorier | Consulter | Exporter |
| :--- | :--- | :--- |
| Nœuds, VM QEMU, conteneurs LXC et modèles | États, vCPU, mémoire et capacité disque déclarée | Rapport JSON horodaté en UTC et résumé dans le terminal |

> **État du projet** — Le mode démonstration et les 38 tests automatisés ont été exécutés avec succès. Une collecte réelle de conteneurs LXC a également réussi en HTTPS local, avec vérification du certificat et jeton en lecture seule. Voir le périmètre exact dans [Validation](docs/VALIDATION.md).

<a id="demarrage-rapide"></a>

## Démarrage rapide

Python **3.10 ou supérieur** suffit. Aucun paquet supplémentaire n’est nécessaire.

```bash
git clone https://github.com/Kofysh/proxmox-inventory.git
cd proxmox-inventory
python3 proxmox_inventory.py --demo
```

Il est également possible de télécharger l’archive depuis **Code → Download ZIP** et d’ouvrir un terminal dans le dossier extrait.

Sous Windows, utiliser `py -3` à la place de `python3` :

```powershell
py -3 proxmox_inventory.py --demo
```

La démonstration ne nécessite ni serveur, ni connexion réseau, ni jeton. Elle utilise des **données fictives** et génère `reports/inventory.json` avec la valeur `"mode": "demo"`.

### Aperçu des résultats

Le jeu de démonstration contient un nœud, trois invités et un modèle :

| Ressource | Type | État | vCPU | Mémoire |
| :--- | :--- | :--- | ---: | ---: |
| `vps-demo-01` | VM QEMU | En cours d’exécution | 2 | 4 Gio |
| `vps-demo-02` | VM QEMU | Arrêtée | 2 | 2 Gio |
| `paymenter-demo` | Conteneur LXC | En cours d’exécution | 2 | 2 Gio |
| `debian-template` | Modèle QEMU | Modèle | 2 | 2 Gio |

Les modèles sont comptés séparément des invités arrêtés. Une métrique absente reste `null` dans le JSON ; elle n’est pas remplacée par zéro.

[Voir le rapport JSON](examples/report-demo.json) · [Voir la sortie du terminal](examples/console-demo.txt)

## Filtrer l’affichage

```bash
python3 proxmox_inventory.py --demo --node pve-lab-01 --status running
```

Le terminal présente un résumé, les nœuds, puis les invités regroupés par nœud. Les sections sont espacées, les états sont traduits en français et les tableaux s’adaptent à la largeur disponible (40 à 120 colonnes). `--node` sélectionne un nom de nœud exact ; `--status` accepte `running` ou `stopped` et concerne uniquement les invités. Les modèles sont sélectionnés selon leur état API mais restent identifiés comme modèles.

**Les filtres ne modifient pas le JSON exporté.** L’inventaire complet reste disponible pour les comparaisons. Les cellules longues passent sur plusieurs lignes. Les notes sont repliées à la largeur du terminal ; aucun code couleur ANSI n’est ajouté aux sorties redirigées.

## Comparer deux inventaires

```bash
python3 proxmox_inventory.py --compare reports/avant.json reports/apres.json
```

Cette commande fonctionne hors ligne, sans jeton ni connexion à Proxmox. Elle écrit `reports/comparison.json` et signale les ressources nouvellement visibles, absentes ou modifiées. Un changement de nœud pour un même VMID apparaît comme une migration, et non comme une suppression suivie d’une création.

Les changements suivis comprennent les états, les noms, le type, le statut de modèle, les vCPU, la mémoire attribuée et la capacité disque déclarée. Pour les nœuds, l’état et la capacité CPU/RAM sont comparés ; l’utilisation instantanée de mémoire est ignorée.

Une démonstration reproductible est fournie :

```bash
python3 proxmox_inventory.py --compare examples/report-demo.json examples/report-demo-after.json
```

[Voir les différences attendues](examples/comparison-demo.json)

Les deux rapports doivent partager la même source et le même mode, utiliser le schéma v1 et être fournis dans l’ordre chronologique. Un rapport de comparaison ne peut pas servir d’inventaire d’entrée. La destination ne peut pas être l’un des fichiers comparés. Un code de sortie `0` signifie que la comparaison a réussi, même si elle trouve des changements.

> Une ressource absente peut simplement être devenue invisible à cause des ACL. La comparaison ne prouve pas sa suppression. Un VMID réutilisé ne permet pas non plus d’identifier avec certitude une recréation.

## Connexion à Proxmox

La collecte réelle repose sur un utilisateur dédié et un jeton API en lecture seule. Le certificat HTTPS est vérifié ; une autorité interne peut être fournie au format PEM.

| Variable | Utilisation |
| :--- | :--- |
| `PVE_URL` | Origine HTTPS de Proxmox, par exemple `https://pve.example.net:8006` |
| `PVE_TOKEN_ID` | Identifiant complet du jeton, sous la forme `utilisateur@realm!jeton` |
| `PVE_TOKEN_SECRET` | Secret du jeton, fourni dans l’environnement |
| `PVE_CA_FILE` | Certificat de l’autorité de confiance interne, si nécessaire |
| `PVE_TIMEOUT` | Délai réseau en secondes ; valeur par défaut : `10` |

Le fichier [`.env.example`](.env.example) décrit la configuration. Il n’est pas chargé automatiquement par le programme.

Une fois les variables définies :

```bash
python3 proxmox_inventory.py --output reports/inventory-live.json
```

**[Consulter le guide de configuration →](docs/INSTALLATION.md)**  
Création du jeton, permissions, certificats, commandes Bash et PowerShell, codes de retour et dépannage.

## Vérifier la connexion

```bash
python3 proxmox_inventory.py --check
```

Le diagnostic vérifie la configuration, réalise les deux requêtes HTTPS autorisées puis valide les données retournées. Il indique l’étape qui échoue et distingue les erreurs DNS, de connexion refusée, de délai et de certificat. **Il ne crée aucun fichier et ne modifie aucune ressource.**

Un succès confirme l’accès aux routes et la validité des données reçues, pas l’exhaustivité du cluster. Une liste vide reste accompagnée d’un avertissement sur les permissions. Le diagnostic s’arrête au premier échec.

## Exécuter en silence

```bash
python3 proxmox_inventory.py --quiet --output reports/inventory-live.json
python3 proxmox_inventory.py --check --quiet
```

`--quiet` supprime l’affichage normal et les avertissements du terminal. Les erreurs restent sur la sortie d’erreur, avec un code de retour non nul. Les rapports JSON conservent toutes les informations et leurs avertissements. Cette option fonctionne aussi avec `--demo` et `--compare`.

## Fonctionnement

Le programme effectue deux appels à l’API :

| Requête | Informations collectées |
| :--- | :--- |
| `GET /api2/json/nodes` | Nœuds et ressources exposées par l’API |
| `GET /api2/json/cluster/resources?type=vm` | VM, conteneurs et modèles accessibles au jeton |

Les réponses sont validées, triées puis converties en un format commun. Le rapport est écrit dans un fichier temporaire avant de remplacer la destination. Si une collecte échoue, l’ancien rapport reste inchangé et le programme renvoie un code d’erreur.

Les redirections HTTP sont refusées. Le secret du jeton n’est inclus ni dans le rapport ni dans les messages d’erreur. Les noms affichés dans le terminal sont débarrassés des caractères de contrôle.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Les **38 tests** couvrent le comptage des ressources, les données manquantes ou invalides, les erreurs d’authentification et de connexion, les paramètres TLS ainsi que l’écriture du rapport. Le transport réseau est simulé : ces tests ne remplacent pas une recette sur le serveur cible.

Le workflow GitHub Actions exécute les tests, la démonstration et la comparaison sous **Linux et Windows**, avec Python **3.10, 3.12 et 3.13**, à chaque push sur `main` et à chaque pull request. Le badge affiche son état réel. Aucun secret Proxmox n’est nécessaire.

Le [document de validation](docs/VALIDATION.md) précise les vérifications réalisées et celles restant à effectuer.

## Organisation du dépôt

| Fichier | Contenu |
| :--- | :--- |
| [`proxmox_inventory.py`](proxmox_inventory.py) | Client API, traitement des données, export et interface en ligne de commande |
| [`tests/`](tests/) | Tests de collecte, diagnostic, mode silencieux, comparaison et erreurs |
| [`.github/workflows/tests.yml`](.github/workflows/tests.yml) | Vérifications automatiques Linux / Windows |
| [`examples/`](examples/) | Données fictives et exemples de résultats |
| [`docs/INSTALLATION.md`](docs/INSTALLATION.md) | Configuration et utilisation sur Proxmox |
| [`docs/CONCEPTION.md`](docs/CONCEPTION.md) | Choix techniques et présentation du fonctionnement |
| [`docs/VALIDATION.md`](docs/VALIDATION.md) | Bilan des essais et recette de l’infrastructure |

## Périmètre et limites

L’inventaire porte sur les ressources **visibles par le jeton**. Une réponse vide ne garantit pas l’absence de machines : les permissions peuvent restreindre les résultats.

La capacité disque reprend le champ `maxdisk` de l’API. Elle ne représente pas nécessairement la somme de tous les disques d’une VM, ni l’espace réellement utilisé. Les deux appels sont successifs et ne constituent pas un instantané atomique du cluster.

L’outil ne modifie aucune ressource. Il ne réalise pas d’audit de sécurité et ne vérifie ni les sauvegardes, ni l’isolation réseau, ni la facturation ou le provisionnement Paymenter. Un ancien rapport peut subsister après une erreur : vérifier le code de retour et la date `generated_at`.

Les rapports réels peuvent contenir des noms de machines et l’adresse de l’API. Le dossier `reports/`, les fichiers `.env` et les certificats PEM sont ignorés par Git ; anonymiser les résultats avant de les partager.

---

**Documentation officielle**  
[API Proxmox VE](https://pve.proxmox.com/wiki/Proxmox_VE_API) · [Utilisateurs et permissions](https://pve.proxmox.com/pve-docs/pveum-plain.html) · [Référence de l’API](https://pve.proxmox.com/pve-docs/api-viewer/index.html)
