"""Classement déterministe des besoins par catégorie de marché.

Premier niveau, explicable et gratuit : des mots-clés issus des libellés réels des PTA
et PPM. L'agent d'imputation (IA) prend le relais pour les libellés non reconnus.
"""

from __future__ import annotations

import re

from app.services.pta_import import norm

# Catégorie → mots-clés (formes normalisées sans accents). L'ordre compte : la première
# catégorie reconnue l'emporte.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("construction", ("construction", "construire", "batiment", "bâtiment", "amenagement")),
    ("rehabilitation", ("rehabilitation", "refection", "renovation")),
    ("etudes", ("etude", "elaboration du plan", "diagnostic", "evaluation d")),
    ("consultants", ("cabinet", "consultant", "recrutement d'un", "assistance technique")),
    ("vehicules", ("vehicule", "moto", "barque", "engin")),
    ("materiel_informatique", ("informatique", "ordinateur", "imprimante", "logiciel", "serveur")),
    ("mobilier", ("mobilier", "meuble", "chaise", "bureau et")),
    ("fournitures_bureau", ("fourniture", "consommable", "papeterie")),
    ("carburant", ("carburant", "lubrifiant", "gasoil", "essence")),
    ("impression", ("impression", "reprographie", "edition", "confection des supports", "tirage")),
    ("restauration", ("restauration", "pause-cafe", "pause cafe", "repas")),
    ("location_salle", ("location de salle", "location d'infrastructure", "location")),
    ("entretien_locaux", ("entretien des bureaux", "entretien des locaux", "nettoyage",
                          "gardiennage")),
    ("maintenance", ("maintenance", "reparation", "entretien")),
]  # fmt: skip


def market_category(label: str) -> str | None:
    text = norm(label)
    for category, keywords in CATEGORY_KEYWORDS:
        for keyword in keywords:
            if re.search(rf"\b{re.escape(norm(keyword))}", text):
                return category
    return None


def normalize_mode(value: str | None) -> str:
    text = norm(value)
    if "mixte" in text:
        return "mixte"
    if "indirect" in text or "consultation" in text or "marche" in text:
        return "indirect"
    return "direct"
