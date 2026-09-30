"""Étapes et délais réglementaires des procédures de passation (Bénin).

Sources :
- loi n° 2020-26 du 29 septembre 2020 portant code des marchés publics (art. 54 : délais
  de remise des offres ; délai d'attente de 10 jours calendaires) ;
- décret n° 2020-600 du 23 décembre 2020 fixant les délais impartis aux organes de
  passation (art. 3), de contrôle (art. 4 DNCMP/DDCMP, art. 5 CCMP) et d'approbation (art. 6) ;
- décret n° 2020-605 du 23 décembre 2020 relatif aux sollicitations de prix (art. 15, 18 à 20) ;
- manuel de procédures de passation des marchés publics de l'ARMP (juin 2023), pour
  l'enchaînement des étapes et les délais qu'il précise.

La procédure elle-même découle du montant et des seuils du décret n° 2020-599 ; les délais
dépendent en outre de l'organe de contrôle compétent et de la publication communautaire.
Une étape dont le délai n'est fixé par aucun texte est marquée `indicative` : sa durée
est un paramètre de planification que la structure ajuste.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.engines.calendar import DEFAULT_CALENDAR, DayUnit, WorkCalendar

OUV, CAL = DayUnit.OUVRABLES, DayUnit.CALENDAIRES
L2020_26 = "Loi n° 2020-26"
D600 = "Décret n° 2020-600"
D605 = "Décret n° 2020-605"
MANUEL = "Manuel de procédures ARMP (2023)"


@dataclass(frozen=True)
class ProcedureStep:
    code: str
    label: str
    duration: int
    unit: DayUnit
    basis: str  # référence réglementaire
    indicative: bool = False
    # Délai minimal entre le début de l'étape et le lancement (publication de l'avis).
    min_lead: tuple[int, DayUnit] | None = None


@dataclass(frozen=True)
class ProcedureTemplate:
    code: str
    before_launch: tuple[ProcedureStep, ...]  # jusqu'à la publication de l'avis
    after_launch: tuple[ProcedureStep, ...]  # de la publication à la notification


@dataclass(frozen=True)
class ScheduledStep:
    code: str
    label: str
    start: date
    end: date
    duration: int
    unit: DayUnit
    basis: str
    indicative: bool


@dataclass(frozen=True)
class Schedule:
    launch_date: date  # publication de l'avis (lancement prévu au PPM)
    preparation_start: date  # début de la préparation du dossier
    steps: tuple[ScheduledStep, ...]


def _control_days(control_body: str, national: int, cell: int) -> int:
    return national if control_body in ("DNCMP", "DDCMP") else cell


def _contract_steps(control_body: str, approval_days: int, approval_basis: str,
                    legal_review: bool = True) -> tuple[ProcedureStep, ...]:  # fmt: skip
    steps = []
    if legal_review:
        steps += [
            ProcedureStep("transmission_contrat", "Transmission du projet de contrat à l'organe de contrôle",
                          1, OUV, f"{D600}, art. 3.9"),
            ProcedureStep("examen_juridique", "Examen juridique et technique du projet de marché",
                          3, OUV, f"{D600}, art. {'4.6' if control_body == 'DNCMP' else '5.4'}"),
        ]  # fmt: skip
    steps += [
        ProcedureStep("signature_attributaire", "Signature du marché par l'attributaire", 3, OUV,
                      f"{D600}, art. 3.10"),
        ProcedureStep("signature_prmp", "Signature par la PRMP et transmission pour visa", 2, OUV,
                      f"{D600}, art. 3.11"),
        ProcedureStep("approbation", "Approbation du marché", approval_days, OUV, approval_basis),
        ProcedureStep("authentification", "Numérotation et authentification", 3, OUV,
                      f"{MANUEL}, étape 11"),
        ProcedureStep("notification", "Notification de l'attribution définitive au titulaire", 2,
                      CAL, f"{D600}, art. 3.12"),
    ]  # fmt: skip
    return tuple(steps)


def _open_call_before_launch(control_body: str, dossier: str) -> tuple[ProcedureStep, ...]:
    """Préparation, contrôle a priori et « bon à lancer » d'un dossier d'appel à concurrence."""
    avis = _control_days(control_body, 4, 3)
    return (
        ProcedureStep("preparation", f"Élaboration du {dossier} (au plus tard 30 jours avant le lancement)",
                      0, CAL, f"{D600}, art. 3.1", min_lead=(30, CAL)),
        ProcedureStep("transmission_dossier", f"Transmission du {dossier} à l'organe de contrôle",
                      0, OUV, f"{D600}, art. 3.2", min_lead=(10, OUV)),
        ProcedureStep("avis_dossier", f"Avis de la {control_body} sur le {dossier}", avis, OUV,
                      f"{D600}, art. {'4.1' if control_body == 'DNCMP' else '5.1'}"),
        ProcedureStep("prise_en_compte", "Prise en compte des observations", 2, OUV,
                      f"{D600}, art. 3.3"),
        ProcedureStep("bon_a_lancer", "« Bon à lancer »", 1, OUV, f"{D600}, art. 5.2 ; {MANUEL}"),
        ProcedureStep("publication", "Retrait du dossier validé et publication de l'avis", 2,
                      OUV, f"{D600}, art. 3.4"),
    )  # fmt: skip


def template_for(
    procedure: str, control_body: str, community: bool, urgent: bool = False
) -> ProcedureTemplate:
    """Étapes réglementaires d'une procédure, selon l'organe de contrôle et la publicité."""
    remise = 15 if urgent else (30 if community else 21)
    remise_basis = f"{L2020_26}, art. 54" + (" (urgence autorisée par la DNCMP)" if urgent else "")
    rapport = _control_days(control_body, 5, 3)
    rapport_basis = f"{D600}, art. {'4.3' if control_body == 'DNCMP' else '5.3'}"

    if procedure == "AOO":
        return ProcedureTemplate(procedure, _open_call_before_launch(control_body, "DAO"), (
            ProcedureStep("remise_offres", "Délai de remise des offres", remise, CAL, remise_basis),
            ProcedureStep("evaluation", "Ouverture des plis et évaluation des offres (COE)", 10, OUV,
                          f"{D600}, art. 3.6"),
            ProcedureStep("avis_evaluation", f"Avis de la {control_body} sur le rapport d'évaluation",
                          rapport, OUV, rapport_basis),
            ProcedureStep("notification_resultats", "Notification des résultats", 1, OUV,
                          f"{D600}, art. 3.7"),
            ProcedureStep("delai_attente", "Délai d'attente (recours)", 10, CAL,
                          f"{L2020_26} ; {D600}, art. 3.8"),
            *_contract_steps(control_body, 5, f"{D600}, art. 6"),
        ))  # fmt: skip

    if procedure == "DRP":
        return ProcedureTemplate(procedure, (
            ProcedureStep("preparation", "Préparation du dossier de DRP", 10, OUV, MANUEL,
                          indicative=True),
            ProcedureStep("avis_dossier", "Avis de la cellule de contrôle sur le dossier", 3, OUV,
                          f"{D600}, art. 5.1"),
            ProcedureStep("publication", "Affichage de l'avis public à candidature", 1, OUV,
                          f"{D605}, art. 13", indicative=True),
        ), (
            ProcedureStep("remise_offres", "Délai de réception des plis", 10, OUV,
                          f"{D605}, art. 15"),
            ProcedureStep("evaluation", "Ouverture et analyse des offres", 5, OUV, f"{D605}, art. 18"),
            ProcedureStep("avis_evaluation", "Validation du PV d'analyse par la cellule de contrôle",
                          3, OUV, f"{D605}, art. 12 ; {D600}, art. 5.3"),
            ProcedureStep("notification_resultats", "Notification et publication des résultats", 2,
                          OUV, f"{D605}, art. 19"),
            ProcedureStep("delai_attente", "Délai avant signature", 5, OUV, f"{D605}, art. 20"),
            *_contract_steps(control_body, 3, f"{D605}, art. 20", legal_review=False),
        ))  # fmt: skip

    if procedure == "DC":
        return ProcedureTemplate(procedure, (
            ProcedureStep("preparation", "Préparation de la demande de cotation", 5, OUV, MANUEL,
                          indicative=True),
        ), (
            ProcedureStep("remise_offres", "Délai de remise des offres (3 devis au moins)", 5, OUV,
                          f"{D605}, art. 15"),
            ProcedureStep("evaluation", "Analyse des offres", 3, OUV, f"{D605}, art. 18"),
            ProcedureStep("notification_resultats", "Publication des résultats", 2, OUV,
                          f"{D605}, art. 19"),
            ProcedureStep("delai_attente", "Délai avant signature", 5, OUV, f"{D605}, art. 20"),
            ProcedureStep("signature_attributaire", "Signature par l'attributaire", 3, OUV, MANUEL),
            ProcedureStep("signature_prmp", "Signature par la PRMP", 2, OUV, MANUEL),
            ProcedureStep("approbation", "Approbation (le cas échéant)", 3, OUV, f"{D605}, art. 20-21"),
            ProcedureStep("notification", "Notification au titulaire", 3, CAL, MANUEL),
        ))  # fmt: skip

    if procedure == "dispense":
        return ProcedureTemplate(procedure, (
            ProcedureStep("expression_besoin", "Expression du besoin", 2, OUV, MANUEL,
                          indicative=True),
        ), (
            ProcedureStep("consultation", "Consultation de trois fournisseurs (préparation des offres)",
                          2, OUV, f"{MANUEL}, §3.1.3"),
            ProcedureStep("commande", "Choix du fournisseur, bon de commande et facture", 2, OUV,
                          MANUEL, indicative=True),
        ))  # fmt: skip

    if procedure == "AMI_DP":
        dp_avis = _control_days(control_body, 5, 3)
        return ProcedureTemplate(procedure, _open_call_before_launch(control_body, "AMI"), (
            ProcedureStep("manifestations", "Réception des manifestations d'intérêt", 10, CAL,
                          f"{L2020_26} ; {MANUEL}, E4"),
            ProcedureStep("evaluation_ami", "Évaluation des manifestations (liste restreinte)", 10,
                          OUV, MANUEL),
            ProcedureStep("avis_ami", f"Avis de la {control_body} sur la liste restreinte", rapport,
                          OUV, rapport_basis),
            ProcedureStep("resultats_ami", "Notification des résultats de l'AMI", 10, CAL,
                          f"{MANUEL}, E5"),
            ProcedureStep("avis_dp", f"Avis de la {control_body} sur la demande de propositions",
                          dp_avis, OUV, MANUEL),
            ProcedureStep("invitation", "Prise en compte des observations et invitation", 4, OUV,
                          f"{D600}, art. 3.3-3.4"),
            ProcedureStep("remise_propositions", "Délai de remise des propositions", remise, CAL,
                          remise_basis),
            ProcedureStep("evaluation_technique", "Évaluation des propositions techniques", 10, OUV,
                          f"{D600}, art. 3.6"),
            ProcedureStep("avis_technique", f"Avis de la {control_body} sur l'évaluation technique",
                          rapport, OUV, rapport_basis),
            ProcedureStep("ouverture_financiere", "Délai avant ouverture des propositions financières",
                          10, CAL, f"{MANUEL}, E11 (5 à 10 jours)"),
            ProcedureStep("negociation", "Évaluation financière et négociation", 7, CAL, MANUEL),
            ProcedureStep("avis_attribution", f"Avis de la {control_body} sur le PV d'attribution",
                          rapport, OUV, rapport_basis),
            ProcedureStep("notification_resultats", "Notification des résultats", 1, OUV,
                          f"{D600}, art. 3.7"),
            ProcedureStep("delai_attente", "Délai d'attente (recours)", 10, CAL,
                          f"{L2020_26} ; {D600}, art. 3.8"),
            *_contract_steps(control_body, 5, f"{D600}, art. 6"),
        ))  # fmt: skip

    if procedure == "SCI":
        return ProcedureTemplate(procedure, _open_call_before_launch(control_body, "AMI"), (
            ProcedureStep("manifestations", "Réception des manifestations d'intérêt", 10, CAL,
                          f"{L2020_26} ; {MANUEL}"),
            ProcedureStep("evaluation", "Évaluation des candidatures (comparaison des CV)", 10, OUV,
                          MANUEL),
            ProcedureStep("negociation", "Négociation avec le consultant retenu", 7, CAL, MANUEL),
            ProcedureStep("avis_attribution", f"Avis de la {control_body} sur le PV d'attribution",
                          rapport, OUV, rapport_basis),
            ProcedureStep("notification_resultats", "Notification des résultats", 1, OUV,
                          f"{D600}, art. 3.7"),
            ProcedureStep("delai_attente", "Délai d'attente (recours)", 10, CAL,
                          f"{L2020_26} ; {D600}, art. 3.8"),
            *_contract_steps(control_body, 5, f"{D600}, art. 6"),
        ))  # fmt: skip

    raise ValueError(f"procédure inconnue : {procedure}")


def schedule(
    template: ProcedureTemplate, need_date: date, calendar: WorkCalendar = DEFAULT_CALENDAR
) -> Schedule:
    """Calendrier à rebours : la notification intervient à la date de besoin."""
    after: list[ScheduledStep] = []
    end = need_date
    for step in reversed(template.after_launch):
        start = calendar.shift(end, -step.duration, step.unit)
        after.append(_scheduled(step, start, end))
        end = start
    launch = end

    before: list[ScheduledStep] = []
    for step in reversed(template.before_launch):
        start = calendar.shift(end, -step.duration, step.unit)
        if step.min_lead is not None:
            start = min(start, calendar.shift(launch, -step.min_lead[0], step.min_lead[1]))
        before.append(_scheduled(step, start, end))
        end = start
    steps = tuple(reversed(before)) + tuple(reversed(after))
    return Schedule(launch_date=launch, preparation_start=steps[0].start, steps=steps)


def _scheduled(step: ProcedureStep, start: date, end: date) -> ScheduledStep:
    return ScheduledStep(step.code, step.label, start, end, step.duration, step.unit, step.basis,
                         step.indicative)  # fmt: skip
