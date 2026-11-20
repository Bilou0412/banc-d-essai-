"""Minuteur pomodoro : phases, historique des sessions, persistance JSON.

L'état du minuteur est calculé paresseusement à partir de `Clock` : chaque
lecture ou action « rattrape » le temps écoulé (transitions à zéro incluses).
Seuls les réglages, les tâches et l'historique sont écrits sur disque.
"""

import datetime as dt
import json
from pathlib import Path

PHASE_TRAVAIL = "travail"
PHASE_PAUSE_COURTE = "pause courte"
PHASE_PAUSE_LONGUE = "pause longue"

STATUT_ARRETE = "arrêté"
STATUT_EN_COURS = "en cours"
STATUT_EN_PAUSE = "en pause"

SANS_TACHE = "sans tâche"

DEFAUTS = {"work": 25, "short": 5, "long": 15, "interval": 4, "auto": False}


class Clock:
    """Temps simulé ; seul `advance` le fait avancer."""

    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += dt.timedelta(seconds=seconds)


def _entier_positif(valeur):
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < 1:
        raise ValueError(f"entier >= 1 attendu, obtenu {valeur!r}")
    return valeur


class PomodoroApp:
    def __init__(self, path, clock):
        self._path = Path(path)
        self._clock = clock
        self._work = DEFAUTS["work"]
        self._short = DEFAUTS["short"]
        self._long = DEFAUTS["long"]
        self._interval = DEFAUTS["interval"]
        self._auto = DEFAUTS["auto"]
        self._taches = []
        self._active = None
        self._history = []
        self._charger()
        self._phase = PHASE_TRAVAIL
        self._statut = STATUT_ARRETE
        self._cycles = 0
        self._tache_session = None
        self._session_work = self._work
        self._t_last = clock.now()
        self._remaining = self._duree(PHASE_TRAVAIL)

    # ------------------------------------------------------------ persistance

    def _charger(self):
        if not self._path.exists():
            return
        texte = self._path.read_text(encoding="utf-8")
        if not texte.strip():
            return
        donnees = json.loads(texte)
        reglages = donnees.get("settings", {})
        self._work = reglages.get("work", self._work)
        self._short = reglages.get("short", self._short)
        self._long = reglages.get("long", self._long)
        self._interval = reglages.get("interval", self._interval)
        self._auto = reglages.get("auto", self._auto)
        self._taches = list(donnees.get("tasks", []))
        self._active = donnees.get("active_task")
        self._history = [
            {
                "task": h["task"],
                "date": dt.date.fromisoformat(h["date"]),
                "minutes": int(h["minutes"]),
            }
            for h in donnees.get("history", [])
        ]

    def _sauver(self):
        donnees = {
            "settings": {
                "work": self._work,
                "short": self._short,
                "long": self._long,
                "interval": self._interval,
                "auto": self._auto,
            },
            "tasks": self._taches,
            "active_task": self._active,
            "history": [
                {"task": s["task"], "date": s["date"].isoformat(), "minutes": s["minutes"]}
                for s in self._history
            ],
        }
        self._path.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------------------------------------ temps

    def _duree(self, phase):
        if phase == PHASE_TRAVAIL:
            return self._work * 60
        if phase == PHASE_PAUSE_COURTE:
            return self._short * 60
        return self._long * 60

    def _entrer(self, phase):
        self._phase = phase
        self._remaining = self._duree(phase)
        if phase == PHASE_TRAVAIL:
            self._session_work = self._work

    def _retime(self):
        """À l'arrêt, le temps restant suit toujours la durée de la phase courante."""
        if self._statut == STATUT_ARRETE:
            self._remaining = self._duree(self._phase)

    def _sync(self):
        now = self._clock.now()
        if self._statut == STATUT_EN_COURS:
            while now - self._t_last >= dt.timedelta(seconds=self._remaining):
                zero = self._t_last + dt.timedelta(seconds=self._remaining)
                self._t_last = zero
                self._a_zero(zero)
                if self._statut != STATUT_EN_COURS:
                    break
            if self._statut == STATUT_EN_COURS:
                self._remaining -= int((now - self._t_last).total_seconds())
        self._t_last = now

    def _a_zero(self, zero):
        if self._phase == PHASE_TRAVAIL:
            self._cycles += 1
            self._history.append({
                "task": SANS_TACHE if self._tache_session is None else self._tache_session,
                "date": zero.date(),
                "minutes": self._session_work,
            })
            self._sauver()
            if self._cycles % self._interval == 0:
                self._entrer(PHASE_PAUSE_LONGUE)
            else:
                self._entrer(PHASE_PAUSE_COURTE)
        else:
            self._entrer(PHASE_TRAVAIL)
            self._tache_session = self._active
        self._statut = STATUT_EN_COURS if self._auto else STATUT_ARRETE

    # ------------------------------------------------------------ état observable

    @property
    def phase(self):
        self._sync()
        return self._phase

    @property
    def status(self):
        self._sync()
        return self._statut

    @property
    def cycles(self):
        self._sync()
        return self._cycles

    @property
    def remaining(self):
        self._sync()
        return self._remaining

    @property
    def work_duration(self):
        return self._work

    @property
    def history(self):
        self._sync()
        return [dict(s) for s in self._history]

    @property
    def today_total(self):
        self._sync()
        aujourd_hui = self._clock.now().date()
        return sum(s["minutes"] for s in self._history if s["date"] == aujourd_hui)

    def task_total(self, name):
        self._sync()
        return sum(s["minutes"] for s in self._history if s["task"] == name)

    @property
    def streak(self):
        self._sync()
        jours = {s["date"] for s in self._history}
        aujourd_hui = self._clock.now().date()
        if aujourd_hui in jours:
            jour = aujourd_hui
        elif aujourd_hui - dt.timedelta(days=1) in jours:
            jour = aujourd_hui - dt.timedelta(days=1)
        else:
            return 0
        serie = 0
        while jour in jours:
            serie += 1
            jour -= dt.timedelta(days=1)
        return serie

    @property
    def active_task(self):
        self._sync()
        return self._active

    # ------------------------------------------------------------ actions

    def start(self):
        self._sync()
        if self._statut == STATUT_ARRETE:
            self._tache_session = self._active
            self._session_work = self._work
            self._statut = STATUT_EN_COURS

    def pause(self):
        self._sync()
        if self._statut == STATUT_EN_COURS:
            self._statut = STATUT_EN_PAUSE

    def resume(self):
        self._sync()
        if self._statut == STATUT_EN_PAUSE:
            self._statut = STATUT_EN_COURS

    def reset(self):
        self._sync()
        self._statut = STATUT_ARRETE
        self._remaining = self._duree(self._phase)

    def skip(self):
        self._sync()
        if self._phase == PHASE_TRAVAIL:
            longue = self._cycles > 0 and self._cycles % self._interval == 0
            self._entrer(PHASE_PAUSE_LONGUE if longue else PHASE_PAUSE_COURTE)
        else:
            self._entrer(PHASE_TRAVAIL)
            self._tache_session = self._active

    def enter_background(self):
        self._sync()

    def enter_foreground(self):
        self._sync()

    def close(self):
        self._sync()
        self._sauver()

    def set_work_duration(self, minutes):
        _entier_positif(minutes)
        self._sync()
        self._work = minutes
        self._retime()
        self._sauver()

    def set_short_break(self, minutes):
        _entier_positif(minutes)
        self._sync()
        self._short = minutes
        self._retime()
        self._sauver()

    def set_long_break(self, minutes):
        _entier_positif(minutes)
        self._sync()
        self._long = minutes
        self._retime()
        self._sauver()

    def set_long_interval(self, n):
        _entier_positif(n)
        self._sync()
        self._interval = n
        self._sauver()

    def set_auto_start(self, auto):
        self._sync()
        self._auto = bool(auto)
        self._sauver()

    def add_task(self, name):
        self._sync()
        if name not in self._taches:
            self._taches.append(name)
        self._sauver()

    def set_active_task(self, name):
        self._sync()
        self._active = name
        self._sauver()

    def delete_task(self, name):
        self._sync()
        if name in self._taches:
            self._taches.remove(name)
        if self._active == name:
            self._active = None
        self._sauver()
