# Budget Intelligence Engine (BIE)

Plateforme de planification budgétaire, de passation des marchés et de suivi de la performance pour les structures publiques du Bénin. Principe central : **une donnée saisie une seule fois alimente le PTA, le PCC et le PPM**.

Le cahier des charges complet est tenu dans un document partagé ; l'analyse des PTA, PCC et PPM réels ayant servi à caler les formats est dans [`docs/analyse-modeles-reels.md`](docs/analyse-modeles-reels.md).

## Ce que fait la version actuelle

| Domaine | Fonction |
| --- | --- |
| Import | Import d'un PTA Excel existant, quel que soit le format du ministère : en-tête, colonnes AE/CP × sources, unité (FCFA ou milliers), niveaux (programme → tâche), contrôle des totaux, anomalies. Validé sur les PTA 2023-2026 de plusieurs ministères. |
| Planification | Arbre programme → objectif → résultat → action → activité budgétaire → activité → tâche → ligne de ressource (quantité × prix unitaire). |
| Prix | Référentiel propre à BIE, extrait de l'**e-répertoire des prix de référence v26.3** (9 732 articles, fourchettes BI–BS, nature économique portée par le code article). La borne retenue (BI ou BS) est choisie par la structure et modifiable ligne par ligne ; tout prix hors fourchette est signalé. |
| Imputation | Nomenclature budgétaire du **décret n° 2014-794** (390 natures de dépense) : validation et recherche. |
| Enveloppes | Autorisé, programmé, reliquat, taux, dépassement ; blocage ou dérogation selon la règle. |
| Marchés | Regroupement des besoins par catégorie sur l'exercice (anti-fractionnement) ; procédure, organe de contrôle (DNCMP/CCMP) et publication UEMOA selon le **décret n° 2020-599** (État et communes) ; calendrier à rebours en jours ouvrables ou calendaires, étape par étape, selon la **loi n° 2020-26**, les **décrets n° 2020-600 et 2020-605** et le **manuel de procédures de l'ARMP (2023)**, chaque étape citant sa base réglementaire. |
| Instruments | Exports Excel du PTA, du PCC (mensuel et trimestriel) et du PPM au format officiel à deux onglets. |
| Gouvernance | Directives des autorités (plafond, interdiction, part minimale, période exclue), héritage entre niveaux. |
| IA | Agent de planification : propose tâches et ressources d'une activité à partir des PTA antérieurs, en cherchant les articles dans l'e-répertoire et la nomenclature ; prix et imputations revérifiés de façon déterministe ; repli sans IA sur l'historique. |

## Architecture

```
backend/
  app/engines/     moteurs purs : costing, budget_rules, procurement, instruments, governance
  app/services/    import PTA, e-répertoire, nomenclature, exports, persistance, agents IA
  app/models/      modèle de données SQLAlchemy
  app/api/         API REST FastAPI
  app/referentials nomenclature (décret 2014-794) et e-répertoire v26.3 extraits
  tests/           tests pytest
frontend/          interface React + TypeScript (Vite)
docs/              analyses et documents de conception
```

Les moteurs sont des fonctions pures `résultat = f(photo du graphe, référentiels)` : le même code sert à la programmation réelle et aux scénarios de simulation. L'IA propose ; les calculs et contrôles restent déterministes ; rien n'est écrit sans validation humaine.

## Lancer en local

Prérequis : Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, PostgreSQL 16 (ou SQLite pour un essai rapide).

```bash
# Serveur
cd backend
uv sync
export BIE_DATABASE_URL="sqlite:///./bie.db"      # ou postgresql+psycopg://…
export BIE_ANTHROPIC_API_KEY="…"                   # facultatif : active l'agent IA
uv run uvicorn app.main:app --reload --port 8000   # API sur http://localhost:8000/docs

# Interface
cd ../frontend
npm install
npm run dev                                        # http://localhost:5173
```

Premiers pas : créer une structure, importer un PTA Excel (menu « Importer un PTA »), charger l'e-répertoire (menu « e-Répertoire des prix »), puis consulter enveloppes et PPM.

## Tests

```bash
cd backend
uv run pytest
uv run ruff check .
```

## Points à valider

- Étapes sans délai fixé par les textes (préparation des dossiers de DRP et de DC, dispense), marquées « indicatif ».
- Fêtes musulmanes (Ramadan, Tabaski, Maouloud) à renseigner chaque année dans le calendrier ouvré.
- Règles propres aux établissements publics (art. 9.2 du décret n° 2020-599).
- Formats d'export exacts attendus par la DGB et l'ARMP.
