# Révisions

Petite application de révision pour les jumeaux : un joueur par enfant, un score
enregistré à chaque série de 20 questions, l'historique pour voir la progression.

**Le site : https://sleclercq.github.io/study_app/** (fait pour le téléphone, marche
aussi sur ordinateur et tablette).

## Sur le téléphone

Ouvrir l'adresse ci-dessus, puis l'ajouter à l'écran d'accueil **avant de créer son
prénom** : elle s'ouvre alors comme une appli, et marche même sans réseau.

- iPhone (Safari) : bouton Partager, puis « Sur l'écran d'accueil ».
- Android (Chrome) : menu ⋮, puis « Installer l'application » ou « Ajouter à l'écran d'accueil ».

Les scores et la progression restent **sur l'appareil** : rien n'est envoyé nulle
part, pas de compte. Pour changer de téléphone ou garder une copie : premier écran,
« Sauvegarde de la progression », Exporter puis Importer sur l'autre appareil.

## Publier une modification

`git push` sur `main`, rien d'autre. La GitHub Action [Site](.github/workflows/site.yml)
lance les tests, vérifie les fichiers d'exercices, construit le site et le publie
(environ une minute). Si quelque chose casse, rien n'est publié : la version en ligne
reste la précédente et GitHub envoie un mail.

Essayer avant de pousser :

```bash
python3 tools/build_site.py --serve
```

puis ouvrir http://localhost:8000. Les tests seuls :

```bash
node --test tests/*.test.mjs
```

## Exercices

| Niveau | Exercice | Ce qu'on travaille |
|---|---|---|
| 4e | Allemand - Vocabulaire du carnet | le vocabulaire du cours, dans les deux sens, article obligatoire |
| 4e | Allemand - Rattrapage 6e et 5e | les 980 mots du manuel, en mode progressif (boîtes de Leitner) |
| 5e | Verbes latins | infinitif et présent de l'indicatif |
| 5e | Verbes anglais irréguliers | base verbale, prétérit, participe passé |
| 5e | Anglais - Phrases à trous | le verbe irrégulier dans la phrase |
| 5e | Français - Accord du participe passé | repérer le COD, accorder |
| 5e | Français - Conjugaison | dire, pouvoir, voir aux quatre modes |

Ajouter un exercice = déposer un fichier JSON dans `data/<matière>/` et pousser.
Voir `CLAUDE.md`.

## L'appli Mac d'origine

La version Python + Tkinter + SQLite tourne toujours en local (`./run.sh`), avec son
propre historique (`study.db`), séparé de celui du site. Elle lit les mêmes fichiers
d'exercices.
