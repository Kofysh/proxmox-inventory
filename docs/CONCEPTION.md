# Conception et présentation du livrable

## Objectif dans le projet B2

Le projet principal porte sur une plateforme VPS reposant sur Proxmox et Paymenter. Cet outil ajoute une fonction indépendante : rendre les ressources virtualisées visibles sous une forme exploitable avant ou après une intervention. Son fonctionnement ne dépend ni d’un paiement ni de l’achat du connecteur Paymenter.

## Parcours des données

1. `main()` lit les arguments. Le mode démonstration choisit une fixture locale ; le mode réel initialise `ProxmoxClient`.
2. Le client vérifie la configuration et initialise un contexte TLS avec vérification du certificat et du nom d’hôte.
3. `get()` envoie les deux requêtes GET autorisées avec le jeton dans l’en-tête HTTP. Le corps des erreurs serveur n’est pas affiché.
4. `build_report()` valide les champs, conserve `null` pour les valeurs absentes, trie les ressources et calcule les compteurs.
5. `write_report()` écrit un fichier temporaire puis remplace la destination après succès.
6. `print_summary()` présente les résultats en Gio et neutralise les caractères de contrôle du terminal.

## Choix à expliquer

**Bibliothèque standard :** pas de dépendance externe à installer ; `urllib` pour HTTPS, `ssl` pour la confiance, `json` pour l’export, `argparse` pour la CLI, `unittest` pour les tests.

**Lecture seule :** l’application n’expose que deux routes GET ; le jeton doit en plus recevoir des droits de lecture. Les deux mesures se complètent.

**Séparation collecte / transformation :** `build_report()` n’a pas besoin de réseau. Cela rend les calculs et les limites testables avec des données fictives.

**Gestion des erreurs :** l’erreur technique est convertie en message utile sans recopier les détails susceptibles de contenir un secret. Un échec de la seconde requête ne génère pas un rapport partiel présenté comme terminé.

**Fichier JSON :** format lisible par l’humain et réutilisable par d’autres programmes. Les octets sont conservés comme unité de référence ; l’affichage convertit en Gio (1 Gio = 1 073 741 824 octets).

## Démonstration suggérée — 5 minutes

1. Présenter le besoin et expliquer l’indépendance vis-à-vis du plugin Paymenter.
2. Lancer `python3 proxmox_inventory.py --demo` en annonçant les données fictives.
3. Montrer le JSON et la distinction entre VM arrêtée et modèle.
4. Lancer les tests puis expliquer un test de refus d’accès et un test de comptage.
5. Si la recette réelle a été effectuée, présenter un résultat anonymisé et sa date ; sinon, expliquer précisément ce qui reste à valider.

## Questions possibles

**Pourquoi pas un jeton root ?** L’outil a seulement besoin de lire l’inventaire ; un compte dédié limite les droits et facilite la révocation.

**Pourquoi ne pas désactiver TLS dans le laboratoire ?** Le jeton transite dans l’en-tête de chaque requête. La vérification du serveur protège la connexion ; une autorité interne peut être ajoutée au magasin de confiance utilisé par le programme.

**Une réponse vide est-elle une preuve d’absence de VM ?** Non. Les permissions peuvent filtrer la liste. Le rapport signale cette limite.

**Le programme automatise-t-il les commandes Paymenter ?** Non. Il produit un inventaire de l’environnement Proxmox. Le connecteur de provisionnement est un composant distinct.

**Les tests prouvent-ils que cela fonctionne chez moi ?** Ils vérifient la logique et les erreurs simulées. Une recette sur l’API réelle reste nécessaire pour valider réseau, certificats, droits et compatibilité avec la version installée.

## Contribution et suite du travail

Cette base a été produite avec l’assistance de ChatGPT. Pour la présenter, comprendre les fonctions, adapter la configuration, réaliser la recette et documenter les modifications effectivement effectuées. Ne pas attribuer à ce livrable le développement de Paymenter ou de son plugin ; respecter les règles de l’établissement concernant l’assistance IA.

La version 1.1 ajoute la comparaison hors ligne et les filtres d’affichage. Évolutions possibles après validation : export CSV et suivi d’une liste de VM attendues. Une extension au contrôle des sauvegardes demanderait de nouvelles routes, de nouveaux critères et des tests adaptés.

## Comparaison des inventaires

`read_inventory()` charge un JSON avec une limite de taille. `validate_inventory()` vérifie son schéma, les identités uniques et les données nécessaires. `compare_inventories()` compare les nœuds par nom et les invités par VMID, ce qui permet de conserver l’identité d’un invité lors d’une migration. Les champs de consommation instantanée sont exclus des changements pour limiter le bruit.

Les filtres sont appliqués dans `print_summary()` après la collecte et l’export ; ils ne créent donc pas d’inventaires partiels. Le workflow CI vérifie les comportements hors réseau sur plusieurs versions Python et deux systèmes d’exploitation.
