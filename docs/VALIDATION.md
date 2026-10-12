# Validation du livrable

## Vérifications effectuées lors de la préparation

- Exécution du mode démonstration : réussie, avec génération d’un JSON valide.
- Résultat attendu du jeu fictif : 1 nœud, 3 invités dont 2 actifs et 1 arrêté, 1 modèle séparé.
- Suite `python3 -m unittest discover -s tests -v` : **30 tests réussis**.
- Le mode démonstration n’instancie pas le client réseau, ce qui est vérifié par un test.
- Les erreurs simulées de configuration, HTTP 401/403/302/500, réseau, délai et TLS sont traitées.
- Les réponses invalides et trop volumineuses sont refusées.
- Une collecte échouée conserve l’ancien rapport et renvoie un code d’échec.

Ces validations portent sur la logique locale et un transport simulé. Ces essais automatisés n’utilisent aucun serveur Proxmox réel, compte Paymenter ni paiement. Une validation réelle distincte est décrite ci-dessous. Les exemples sont synthétiques, et non des résultats anonymisés d’un déploiement existant.

## Comparaison et filtres

Les essais locaux couvrent aussi les ajouts, absences et modifications, les migrations entre nœuds, le rejet de sources incompatibles et d’horodatages inversés, la conservation des rapports d’entrée et l’exécution sans réseau. Les filtres d’affichage conservent l’ensemble des ressources dans le JSON.

La suite teste les réponses HTTP tronquées et le passage du chemin de l’autorité personnalisée au contexte TLS, ainsi que les erreurs de chargement. Le test du chemin CA emploie un mock : il ne démontre pas une négociation TLS réelle avec un certificat interne.

## Vérifications continues

Le workflow `.github/workflows/tests.yml` lance la suite, le mode démonstration et une comparaison sur Ubuntu et Windows avec Python 3.10, 3.12 et 3.13. Consulter l’onglet Actions pour connaître le résultat de chaque exécution ; l’existence du workflow n’implique pas que toutes les exécutions ont réussi.

## Validation réelle du 13 octobre 2026

La version du commit `a639f491fe2bba210b4e9fccff0ee637d9cf90e5` a été exécutée depuis le serveur Proxmox VE 9.2.21, avec un utilisateur et un jeton temporaires dédiés, le rôle `PVEAuditor` et la séparation des privilèges activée.

| Vérification | Résultat observé |
|---|---|
| HTTPS local sur le port 8006 | Réussi avec validation du certificat par l’autorité interne |
| Lecture des nœuds et conteneurs LXC | Réussie avec le client du projet et les deux routes prévues |
| Deux collectes et exports JSON | Réussis ; rapports conservés uniquement sur le serveur |
| Comparaison des collectes | Aucun changement sur les champs suivis |
| Jeton volontairement invalide | Refus HTTP 401 |
| Adresse publique depuis le serveur | Échec : résolution interne et connexion refusée sur le port 443 |

Le pilote de recette a appelé le client, la normalisation, l’export et la comparaison du module ; il ne constitue pas une validation de bout en bout de toutes les options CLI. Aucun invité n’a été modifié. Les VM QEMU, les modèles et les changements réels de configuration restent couverts uniquement par les jeux synthétiques. Aucun secret, inventaire réel, nom d’hôte ou adresse réseau de cette infrastructure n’est publié.

La présentation du terminal a été améliorée après cette recette : regroupement par nœud, tableaux adaptés à la largeur, états français, valeurs mémoire en Gio dans les comparaisons. Les 30 tests existants passent ; les rendus de démonstration ont été vérifiés à 60 et 80 colonnes.

## Recette complémentaire à effectuer

Le tableau ci-dessous décrit la recette complète depuis le poste d’exploitation ; les résultats locaux déjà obtenus figurent dans la section précédente.

| Vérification | Critère attendu | État initial |
|---|---|---|
| Accès au serveur | Connexion HTTPS depuis le réseau autorisé, certificat validé | À effectuer |
| Jeton de lecture | Utilisateur et jeton dédiés ; ACL de lecture adéquates | À effectuer |
| Inventaire réel | VM et nœuds visibles conformes au périmètre autorisé dans Proxmox | À effectuer |
| Ressources | vCPU et mémoire comparés à l’interface ; portée de `maxdisk` comprise | À effectuer |
| Changement d’état | Une modification manuelle autorisée apparaît au prochain inventaire | À effectuer |
| Droits limités | Réduction contrôlée du périmètre et observation de la visibilité | À effectuer |
| Refus d’authentification | Un secret volontairement invalide produit un échec explicite | À effectuer |
| Export | JSON horodaté, mode live, code de retour 0 | À effectuer |
| Confidentialité du rendu | Rapport de démonstration ou rapport réel anonymisé avant remise | À effectuer |

Pour chaque essai réalisé, noter la date, la version de Proxmox, la version Python, la commande sans secret, le code de retour et le résultat observé. Conserver les données brutes localement. Le fichier `reports/` est ignoré par Git.

## Limites connues

L’outil ne démontre pas que l’ensemble de la plateforme VPS est sécurisé. Il n’évalue ni l’isolation réseau, ni la restauration de sauvegardes, ni le fonctionnement du plugin Paymenter. Son résultat reste limité aux informations exposées par l’API et aux droits du jeton.

## Version 1.2.0 — diagnostic et exécution silencieuse

La suite locale comporte **38 tests**, tous réussis. Les huit nouveaux tests couvrent la classification des exceptions réseau directes et encapsulées, la suppression des détails privés, les deux routes du diagnostic, l’absence d’écriture, les données invalides, les listes vides, l’arrêt au premier échec, les combinaisons d’arguments interdites et les exports silencieux.

Ces nouvelles fonctions sont validées avec un transport simulé. La recette réelle décrite plus haut concerne le commit indiqué dans cette section ; elle n’a pas été répétée avec la version 1.2.0. Aucun nouveau compte ou jeton Proxmox n’a été créé pour cette mise à jour.
