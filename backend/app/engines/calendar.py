"""Calendrier ouvré pour le calcul des délais réglementaires.

Les textes (loi n° 2020-26, décrets n° 2020-600 et 2020-605) expriment les délais tantôt
en jours calendaires, tantôt en jours ouvrables. Un jour ouvrable exclut samedis,
dimanches et jours fériés.

Jours fériés du Bénin pris en compte :
- à date fixe : 1er janvier, 10 janvier (fête des religions endogènes), 1er mai,
  1er août (fête nationale), 15 août, 1er novembre, 25 décembre ;
- liés à Pâques : lundi de Pâques, Ascension, lundi de Pentecôte ;
- les fêtes musulmanes (Ramadan, Tabaski, Maouloud) dépendent de l'observation lunaire :
  leurs dates sont à renseigner chaque année (`extra_holidays`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from functools import lru_cache


class DayUnit(StrEnum):
    OUVRABLES = "ouvrables"
    CALENDAIRES = "calendaires"


FIXED_HOLIDAYS = ((1, 1), (1, 10), (5, 1), (8, 1), (8, 15), (11, 1), (12, 25))


def easter(year: int) -> date:
    """Dimanche de Pâques (algorithme de Meeus/Jones/Butcher, calendrier grégorien)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(year, month, day)


@lru_cache
def legal_holidays(year: int) -> frozenset[date]:
    days = {date(year, m, d) for m, d in FIXED_HOLIDAYS}
    sunday = easter(year)
    days |= {sunday + timedelta(days=1), sunday + timedelta(days=39), sunday + timedelta(days=50)}
    return frozenset(days)


@dataclass(frozen=True)
class WorkCalendar:
    extra_holidays: frozenset[date] = field(default_factory=frozenset)

    def is_working_day(self, day: date) -> bool:
        return (
            day.weekday() < 5
            and day not in legal_holidays(day.year)
            and day not in self.extra_holidays
        )

    def shift(self, start: date, amount: int, unit: DayUnit) -> date:
        """Avance (amount > 0) ou recule (amount < 0) du nombre de jours demandé."""
        if unit == DayUnit.CALENDAIRES:
            return start + timedelta(days=amount)
        step = 1 if amount >= 0 else -1
        day, remaining = start, abs(amount)
        while remaining:
            day += timedelta(days=step)
            if self.is_working_day(day):
                remaining -= 1
        return day


DEFAULT_CALENDAR = WorkCalendar()
