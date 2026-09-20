# Sources des exercices

Photos des cours, carnets de vocabulaire et feuilles d'exercices dont sont tirés
les fichiers `data/*.json`. Rien ici n'est lu par l'application : c'est la matière
première, gardée pour vérifier ou compléter une liste plus tard.

**Les images sont ignorées par git** (volume, et ce sont des pages de cahier des
enfants). Elles existent donc seulement sur ce Mac : pensez-y avant de formater.

```
5e/                             photos 2025-2026 (latin, anglais, français)
4e/2026-09-20_carnets/
    jumeau1/  IMG_5787..5790    chapitre sport, carnet du 1er jumeau
    jumeau2/  IMG_5791..5794    chapitre sport, carnet du 2e jumeau
```

Convention : une transcription = un dossier `AAAA-MM-JJ_sujet/`, un sous-dossier
par carnet quand les deux carnets sont photographiés.

## Ajouter une leçon d'allemand à partir du carnet

1. Photographier les pages, déposer les images dans un nouveau dossier daté sous `4e/`.
2. Demander à Claude Code : « transcris les photos de `data/_sources/4e/<dossier>` et
   ajoute-les à `data/allemand_carnet.json` ». Claude convertit le HEIC lui-même
   (`sips`), relit l'écriture, complète les articles der/die/das manquants, et
   signale ce qu'il n'a pas su lire plutôt que d'inventer.
3. Relancer l'appli : les mots nouveaux apparaissent, l'historique et les cases
   cochées sont conservés (`db.seed_exercises` est incrémental).

Quand les deux carnets ne disent pas la même chose, tout est conservé : la version
la plus juste devient la réponse attendue, l'autre est acceptée via `alt_source` /
`alt_target`, et le champ `_carnet` de chaque mot garde la trace de son origine.
