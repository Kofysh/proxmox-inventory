# Validation du livrable

## Vérifications effectuées lors de la préparation

- Exécution du mode démonstration : réussie, avec génération d’un JSON valide.
- Résultat attendu du jeu fictif : 1 nœud, 3 invités dont 2 actifs et 1 arrêté, 1 modèle séparé.
- Suite `python3 -m unittest discover -s tests -v` : **30 tests réussis**.
- Le mode démonstration n’instancie pas le client réseau, ce qui est vérifié par un test.
- Les erreurs simulées de configuration, HTTP 401/403/302/500, réseau, délai et TLS sont traitées.
- Les réponses invalides et trop volumineuses sont refusées.
- Une collecte échouée conserve l’ancien rapport et renvoie un code d’échec.

Ces validations portent sur la logique locale et un transport simulé. Aucun serveur Proxmox réel, compte Paymenter ni paiement n’a été utilisé lors de ces essais. Les exemples sont synthétiques, et non des résultats anonymisés d’un déploiement existant.

## Comparaison et filtres

Les essais locaux couvrent aussi les ajouts, absences et modifications, les migrations entre nœuds, le rejet de sources incompatibles et d’horodatages inversés, la conservation des rapports d’entrée et l’exécution sans réseau. Les filtres d’affichage conservent l’ensemble des ressources dans le JSON.

La suite teste les réponses HTTP tronquées et le passage du chemin de l’autorité personnalisée au contexte TLS, ainsi que les erreurs de chargement. Le test du chemin CA emploie un mock : il ne démontre pas une négociation TLS réelle avec un certificat interne.

## Vérifications continues

Le workflow `.github/workflows/tests.yml` lance la suite, le mode démonstration et une comparaison sur Ubuntu et Windows avec Python 3.10, 3.12 et 3.13. Consulter l’onglet Actions pour connaître le résultat de chaque exécution ; l’existence du workflow n’implique pas que toutes les exécutions ont réussi.

## Recette à effectuer sur l’infrastructure personnelle

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
