# Sources des exercices

Photos des cours, carnets de vocabulaire et pages de manuel dont sont tirés les
fichiers d'exercices de `data/`. Rien ici n'est lu par l'application : c'est la
matière première, gardée pour vérifier ou compléter une liste plus tard.

**Les images et PDF sont ignorés par git** (volume, pages de cahier des enfants,
pages de manuel sous droits). Ils n'existent que sur ce Mac : pensez-y avant de
changer d'ordinateur.

```
allemand/
    carnets_4e/2026-09-20/
        jumeau1/  IMG_5787..5790           chapitre sport, carnet du 1er jumeau
        jumeau2/  IMG_5791..5794           chapitre sport, carnet du 2e jumeau
    manuel_fantastisch_neu/
        1re_annee_6e/lexique_1..3.pdf      lexique allemand-français de 6e
        2e_annee_5e/lexique_1..3.pdf       lexique allemand-français de 5e
anglais/5e/IMG_4443_verbes_irreguliers.HEIC
francais/5e/IMG_4445_cours_accord_participe_passe.HEIC
francais/5e/IMG_4446_exercice_accord_participe_passe.HEIC
latin/5e/IMG_4441_present_indicatif.HEIC
```

Convention : un dossier par matière ; pour les carnets, un dossier daté par
transcription et un sous-dossier par carnet quand les deux sont photographiés.

## Ajouter une leçon d'allemand à partir du carnet

1. Photographier les pages, déposer les images dans un nouveau dossier daté sous
   `allemand/carnets_4e/`.
2. Demander à Claude Code : « transcris les photos de `data/_sources/allemand/carnets_4e/<dossier>`
   et ajoute-les à `data/allemand/carnet_4e.json` ». Claude convertit le HEIC lui-même,
   relit l'écriture, complète les articles der/die/das manquants, signale ce qu'il
   n'a pas su lire plutôt que d'inventer, et ce qui n'est que dans un des deux carnets.
3. Relancer l'appli : les mots nouveaux apparaissent, l'historique et les cases
   cochées sont conservés.

## Lexique du manuel (rattrapage)

Les PDF du manuel se transforment en exercice avec `tools/import_lexique_fantastisch.py`
(commande complète dans `CLAUDE.md`). Pour le lexique de 4e ou de 3e, même outil,
une option `--annee` de plus.
