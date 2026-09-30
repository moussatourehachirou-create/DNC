# Analyse des PTA, PCC et PPM réels (2023-2026)

Fichiers fournis par la maîtrise d'ouvrage (non versionnés dans ce dépôt) : INRAB (PTAB 2023 et base de calcul, PTA 2026), MESRS, MESTFP, MIC, MJL, MISP, MND, MPMEPE et programmes 091 et 099 (2025).

## Constats clés

1. **Chaque ministère a son propre format.** Mêmes concepts, mais colonnes, libellés, niveaux et unités différents. L'import repose donc sur des **profils de correspondance** par structure, avec détection assistée par l'IA des colonnes et de la hiérarchie.
2. **La hiérarchie est portée par un code à points**, dont la profondeur donne le niveau :

   | Profondeur | MESRS / MESTFP (2025) | INRAB (2026) |
   | --- | --- | --- |
   | 0 | Programme (054, 058) | Programme (36) |
   | 1 | Objectif spécifique | Action |
   | 2 | Résultat | Activité budgétaire |
   | 3 | Action | Activité |
   | 4 | Activité budgétaire | Tâche |
   | 5 | Activité opérationnelle | — |
   | 6 | Tâche | — |

   Les libellés portent souvent un préfixe (« Activité opérationnelle : … »), avec des fautes de frappe fréquentes (« opérattionnelle », « actvité »). D'autres formats (MISP, MIC, MJL) utilisent des codes budgétaires numériques sans points ou une colonne « Rubrique ».
3. **Unités hétérogènes** : FCFA (INRAB, PPM) ou **milliers de FCFA** (MESRS, MESTFP, MJL). Le profil d'import doit fixer l'unité.
4. **Montants par source et par nature de crédit** : AE et CP, chacun ventilé en BN (budget national) / Dons / Emprunts, parfois « Fonds propres / autres ressources PTF » et « Ressources propres » (INRAB).
5. **Imputation budgétaire** :
   - au niveau activité budgétaire : code complet segmenté, par exemple `021058001029 210012001000000 1 0160` (programme/action/activité, classification administrative, source, fonction) ;
   - au niveau tâche : nature économique à 4 chiffres (`6313`, `6114`, `6013`), parfois plusieurs sur une même tâche (`6114 6012`).
6. **Colonnes récurrentes du PTA** : période d'exécution (texte libre « Janv-Déc », « Mai-Mai » ou dates de début et de fin), poids (%), structure responsable, structures associées, mode d'exécution (Direct / Indirect / Mixte, parfois « Mode direct »), indicateurs, valeurs cibles, ODD, arrimage PAG, sensibilité genre, sensibilité climat, observations.
7. **Les tâches sont souvent des étapes sans coût** (« Actualisation des TDR », « Rédaction du rapport ») ; seules certaines portent un montant. Le poids (%) sert au suivi de l'exécution physique.
8. **La base de calcul INRAB 2023** contient exactement nos lignes de ressource : libellé, quantité, prix unitaire, montant, regroupés par activité et sous-activité. C'est le meilleur corpus pour l'historique des prix et la proposition de tâches et ressources.

## PCC (plan de consommation des crédits)

- MESRS / MESTFP : même arborescence que le PTA, ventilation **trimestrielle** (T1 à T4).
- MIC / MJL : ventilation **mensuelle** (janvier à décembre), éclatée par source et article (nature).
- Conclusion : le PCC se calcule à partir des lignes datées ; l'export propose les deux granularités.

## PPM / PPMP

- Deux onglets : « Fournitures, travaux, services » et « Prestations intellectuelles ».
- Données de base : référence (par exemple `F_DPAF_104376`, `PI_SGM_104838`), description, type (T, F, S), mode de passation, **montant estimatif HT**, source (BN, BA, FE, D…), ligne d'imputation, organe de contrôle (CCMP, DNCMP), autorisation d'engagement (annuelle ou pluriannuelle).
- Calendrier : une colonne de date par étape (environ 12 pour fournitures, travaux et services ; environ 26 pour les prestations intellectuelles, AMI puis demande de propositions).
- Lien au PTA : parfois un code PTA ou « P1(Tâche 2.2.11.5) », souvent absent. **La traçabilité PTA → PPM est aujourd'hui manuelle et fragile** ; c'est ce que BIE résout.
- Les classeurs MESRS contiennent aussi des onglets « SEUILS DISPENSE » et « DEROGATION ».

## Seuils constatés dans les PPM 2025 (montants HT)

| Mode | Type | Plage observée (FCFA HT) |
| --- | --- | --- |
| Demande de cotation (DC) | F, S, T, PI | 4,1 M à 10,2 M |
| DRP | F, S | 10,2 M à 69,5 M |
| DRP | PI | 8,5 M à 49,6 M |
| DRP | T | 15,8 M à 162,7 M |
| Appel d'offres ouvert (national) | F, S | à partir de 84,7 M |
| Appel d'offres ouvert | T | à partir de 241,5 M |
| AMI (puis DP) | PI | 4,2 M à 68,6 M |
| MED / entente directe | F, S | 4,2 M à 289,8 M |

Ces plages alimentent le référentiel provisoire `BENIN_2020_599_PROVISOIRE` du moteur des marchés, **à valider avec le décret n° 2020-599 et l'ARMP**. Seuils vérifiés : dispense ≤ 4 M, DC ≤ 10 M.

## Qualité des données observée

- Libellés de modes de passation non normalisés (« DRP », « Demande de Renseignements et de Prix (DRP) », « Demande de Renseignement et de prix (DRP) »).
- Valeurs aberrantes (DC à 20,5 milliards ; un montant saisi dans la colonne du mode de passation).
- Codes avec guillemets, espaces insécables, points finaux ; imputations multiples dans une cellule.

L'import doit normaliser ces valeurs, signaler les anomalies dans une zone de contrôle et ne rien intégrer sans validation.

## Conséquences pour BIE

- Modèle hiérarchique générique à niveaux nommés et configurables par structure (programme → objectif spécifique → résultat → action → activité budgétaire → activité opérationnelle → tâche → ligne de ressource).
- Ligne de ressource optionnelle : une tâche peut porter un montant global (reprise d'anciens PTA) ou des lignes quantité × prix unitaire (nouvelle programmation).
- Unités et sources de financement paramétrables par profil d'import.
- Export PPM au format officiel à deux onglets, calendrier par étape.
