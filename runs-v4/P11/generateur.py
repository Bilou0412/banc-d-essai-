"""Générateur de situations — sonde P11 (classeur collaboratif hors ligne).

Joue au hasard (rng semé) des actions de trois personnes (alice propriétaire, Paris ;
bob écriture, UTC ; carol lecture, UTC) sur un réseau simulé, et observe après chaque
action ce que voient les personnes concernées.
"""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
W = "écriture"
R = "lecture"

PEOPLE = ["alice", "bob", "carol"]
CELLS = ["A1", "A2", "A3", "B1", "B2", "C1"]
TEXTS = ["42", "0", "4", "2.5", "-3", "Budget", "abc", "a,b", 'dit "oui"', "Été à Noël",
         "2026-01-15 12:00", "2026-07-01 12:00", "2026-03-15", "2026-03-29 02:30",
         "2026-10-25 02:30"]
FORMULAS = ["=A1+A2", "=A1*2", "=A1/B1", "=A1+1", "=B1", "=A1", "=SOMME(A1:A3)",
            "=SOMME(A1:B2)", "=A1-A2-A3", "=-(A1+1)", "=(A1+A2)*2", "=B1-A1",
            "=MAINTENANT()", "=A1+", "=(A1+2", "=", "=A1 A2", "=Feuille2!A1",
            "=Inexistante!A1", "=Feuille1!A1", "=Ventes!A1", "=C1+1"]
SHEET_NAMES = ["Feuille1", "Feuille2", "Ventes", "FEUILLE2", "Dépenses", "Brouillon"]
TZS = ["Europe/Paris", "UTC", "America/New_York", "Asia/Kolkata", "Pacific/Kiritimati",
       "Pacific/Pago_Pago", "Australia/Sydney"]
CSVS = [b"1,2\nx,y\n", b"25\n", b"5,=A1+1\n", b'"12,5",x\n', b"1,,3\n",
        "Café,Noël\n".encode("utf-8"), b"2026-01-15T12:00:00+00:00\n",
        b"2026-07-01 12:00\n", b'a,b\nc,"d\ne,f\n', b"1,2\r\nx,y\r\n",
        b'"a\nb",c\nd\n', "﻿Café,x\n".encode("utf-8"), b"", b"7\n"]
STARTS = [datetime(2026, 1, 15, 10, 0, tzinfo=UTC), datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
          datetime(2026, 3, 29, 0, 30, tzinfo=UTC), datetime(2026, 10, 25, 0, 30, tzinfo=UTC)]


def _j(x):
    """Rend une valeur JSON-compatible, sans repr d'objet."""
    if x is None or isinstance(x, (bool, int, str)):
        return x
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            return str(x)
        return round(x, 9)
    if isinstance(x, (list, tuple)):
        return [_j(e) for e in x]
    if isinstance(x, dict):
        return {str(k): _j(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (bytes, bytearray)):
        return {"octets": len(x)}
    return "?"


def _safe(f, default="refusé"):
    try:
        return _j(f())
    except Exception:
        return default


class _Sim:
    def __init__(self, app, rng):
        self.app = app
        self.rng = rng
        self.start = rng.choice(STARTS)
        self.clock = app.Clock(self.start)
        self.net = app.Network()
        self.server = app.Server(self.net, self.clock, owner="alice")
        self.clients = {
            "alice": app.Client(self.net, self.clock, "alice", tz="Europe/Paris"),
            "bob": app.Client(self.net, self.clock, "bob", tz="UTC"),
            "carol": app.Client(self.net, self.clock, "carol", tz="UTC"),
        }
        self.net.deliver_all()
        self.clients["alice"].set_right("bob", "Feuille1", W)
        self.clients["alice"].set_right("carol", "Feuille1", R)
        self.net.deliver_all()
        self.offline = set()
        self.versions = {}      # mon nom -> id rendu par app
        self.vcount = 0

    # ------------------------------------------------------------ observations
    def known_sheets(self, c):
        s = _safe(c.sheets, [])
        return s if isinstance(s, list) else []

    def cell_view(self, c, sheet, refs):
        out = {}
        for ref in refs:
            out[ref] = {
                "contenu": _safe(lambda: c.content(ref, sheet=sheet)),
                "valeur": _safe(lambda: c.value(ref, sheet=sheet)),
                "erreur": _safe(lambda: c.error(ref, sheet=sheet)),
            }
            cf = _safe(lambda: c.conflict(ref, sheet=sheet), None)
            raw = None
            try:
                raw = c.conflict(ref, sheet=sheet)
            except Exception:
                raw = None
            if raw is not None:
                out[ref]["conflit"] = {
                    "écartée": _safe(lambda: raw.discarded),
                    "par": _safe(lambda: raw.discarded_by),
                }
            elif cf not in (None, "?"):
                out[ref]["conflit"] = cf
        return out

    def person_view(self, name, sheet=None, refs=None):
        c = self.clients[name]
        sheets = self.known_sheets(c)
        if sheet is None:
            sheet = sheets[0] if sheets and "Feuille1" not in sheets else "Feuille1"
        refs = refs or CELLS
        alerts = []
        try:
            for a in c.alerts():
                alerts.append([_j(getattr(a, "kind", None)), _j(getattr(a, "sheet", None)),
                               _j(getattr(a, "cell", None)), _j(getattr(a, "line", None))])
        except Exception:
            alerts = "refusé"
        if isinstance(alerts, list):
            alerts.sort(key=lambda e: str(e))
        return {
            "personne": name,
            "feuilles": sorted(sheets),
            "feuille_vue": sheet,
            "cellules": self.cell_view(c, sheet, refs),
            "connexion": _safe(c.connection_status),
            "en_attente": _safe(c.pending_count),
            "annuler": _safe(c.can_undo),
            "rétablir": _safe(c.can_redo),
            "alertes": alerts,
            "présence": _safe(c.presence),
            "droits": {p: _safe(lambda p=p: c.right(p, sheet)) for p in PEOPLE},
        }

    def history_view(self, name, sheet=None):
        c = self.clients[name]
        try:
            h = c.history(sheet=sheet) if sheet else c.history()
            return [[_j(getattr(v, "author", None)), _j(getattr(v, "timestamp", None)),
                     _j(getattr(v, "kind", None))] for v in h]
        except Exception:
            return "refusé"

    def everyone_cells(self, sheet, refs):
        return {n: self.cell_view(self.clients[n], sheet, refs) for n in PEOPLE}

    # ------------------------------------------------------------ choix
    def pick_person(self):
        return self.rng.choice(PEOPLE)

    def pick_sheet(self, name):
        sheets = self.known_sheets(self.clients[name])
        pool = list(sheets) + ["Feuille1"]
        if self.rng.random() < 0.15:
            pool.append(self.rng.choice(SHEET_NAMES))
        return self.rng.choice(pool)

    def pick_text(self):
        r = self.rng.random()
        if r < 0.45:
            return self.rng.choice(TEXTS)
        if r < 0.9:
            return self.rng.choice(FORMULAS)
        return str(self.rng.randint(-50, 50))

    # ------------------------------------------------------------ une action
    def step(self):
        rng = self.rng
        kind = rng.choices(
            ["set", "clear", "sync", "deliver_from", "off", "on", "advance", "tz",
             "add_sheet", "delete_sheet", "rename_sheet", "set_right", "select",
             "undo", "redo", "resolve", "reopen", "history", "open_version",
             "restore", "export", "import", "activate"],
            weights=[22, 3, 8, 4, 4, 5, 3, 2, 3, 2, 3, 3, 2, 5, 3, 3, 1, 3, 2, 2, 3, 3, 2],
        )[0]
        p = self.pick_person()
        c = self.clients[p]

        if kind == "set":
            sheet = self.pick_sheet(p) if rng.random() < 0.3 else "Feuille1"
            ref = rng.choice(CELLS)
            text = self.pick_text()
            action = f"{p}.set_cell({ref!r}, {text!r}, sheet={sheet!r})"
            res = _safe(lambda: c.set_cell(ref, text, sheet=sheet), "refusé")
            if res == "refusé":
                return action, "refusé"
            return action, self.person_view(p, sheet)

        if kind == "clear":
            ref = rng.choice(CELLS)
            action = f"{p}.clear({ref!r})"
            if _safe(lambda: c.clear(ref)) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, "Feuille1")

        if kind == "sync":
            action = "réseau.deliver_all()"
            if _safe(self.net.deliver_all) == "refusé":
                return action, "refusé"
            return action, self.everyone_cells("Feuille1", CELLS)

        if kind == "deliver_from":
            action = f"réseau.deliver_from({p!r})"
            if _safe(lambda: self.net.deliver_from(p)) == "refusé":
                return action, "refusé"
            return action, self.everyone_cells("Feuille1", CELLS)

        if kind == "off":
            action = f"réseau.disconnect({p!r})"
            if _safe(lambda: self.net.disconnect(p)) == "refusé":
                return action, "refusé"
            self.offline.add(p)
            return action, {"connexion": _safe(c.connection_status), "présence": _safe(c.presence)}

        if kind == "on":
            if self.offline and rng.random() < 0.8:
                p = rng.choice(sorted(self.offline))
                c = self.clients[p]
            action = f"réseau.reconnect({p!r}); deliver_all()"
            if _safe(lambda: self.net.reconnect(p)) == "refusé":
                return action, "refusé"
            self.offline.discard(p)
            if _safe(self.net.deliver_all) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, "Feuille1")

        if kind == "advance":
            minutes = rng.choice([1, 5, 30, 60, 120, 60 * 24, 60 * 24 * 170])
            action = f"horloge.advance(minutes={minutes})"
            if _safe(lambda: self.clock.advance(timedelta(minutes=minutes))) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, "Feuille1")

        if kind == "tz":
            tz = rng.choice(TZS)
            action = f"{p}.set_timezone({tz!r})"
            if _safe(lambda: c.set_timezone(tz)) == "refusé":
                return action, "refusé"
            return action, {"cellules": self.cell_view(c, "Feuille1", CELLS),
                            "historique": self.history_view(p)}

        if kind == "add_sheet":
            name = rng.choice(SHEET_NAMES)
            action = f"{p}.add_sheet({name!r})"
            if _safe(lambda: c.add_sheet(name)) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, name, ["A1", "B2"])

        if kind == "delete_sheet":
            name = self.pick_sheet(p)
            action = f"{p}.delete_sheet({name!r})"
            if _safe(lambda: c.delete_sheet(name)) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, "Feuille1")

        if kind == "rename_sheet":
            old = self.pick_sheet(p)
            new = rng.choice(SHEET_NAMES)
            action = f"{p}.rename_sheet({old!r}, {new!r})"
            if _safe(lambda: c.rename_sheet(old, new)) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, new)

        if kind == "set_right":
            who = rng.choice(PEOPLE)
            sheet = self.pick_sheet(p)
            level = rng.choice([W, R])
            action = f"{p}.set_right({who!r}, {sheet!r}, {level!r})"
            if _safe(lambda: c.set_right(who, sheet, level)) == "refusé":
                return action, "refusé"
            return action, {"droits": {q: _safe(lambda q=q: c.right(q, sheet)) for q in PEOPLE},
                            "alertes": sorted(str(k) for k in _safe(
                                lambda: [a.kind for a in c.alerts()], []) or [])}

        if kind == "select":
            ref = rng.choice(CELLS)
            sheet = self.pick_sheet(p)
            action = f"{p}.select({ref!r}, sheet={sheet!r}); deliver_all()"
            if _safe(lambda: c.select(ref, sheet=sheet)) == "refusé":
                return action, "refusé"
            _safe(self.net.deliver_all)
            return action, {n: _safe(self.clients[n].presence) for n in PEOPLE}

        if kind == "undo":
            action = f"{p}.undo()"
            if _safe(c.undo) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, "Feuille1")

        if kind == "redo":
            action = f"{p}.redo()"
            if _safe(c.redo) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, "Feuille1")

        if kind == "resolve":
            ref = rng.choice(CELLS)
            use = rng.random() < 0.5
            action = f"{p}.resolve_conflict({ref!r}, use_discarded={use})"
            if _safe(lambda: c.resolve_conflict(ref, use_discarded=use)) == "refusé":
                return action, "refusé"
            return action, self.person_view(p, "Feuille1", [ref])

        if kind == "reopen":
            action = f"{p}.reopen()"
            try:
                c2 = c.reopen()
            except Exception:
                return action, "refusé"
            if c2 is None:
                return action, "refusé"
            self.clients[p] = c2
            return action, self.person_view(p, "Feuille1")

        if kind == "history":
            sheet = self.pick_sheet(p)
            action = f"{p}.history(sheet={sheet!r})"
            h = self.history_view(p, sheet)
            if h != "refusé":
                try:
                    hv = c.history(sheet=sheet)
                    if hv:
                        self.vcount += 1
                        idx = rng.randrange(len(hv))
                        self.versions[f"v{self.vcount}"] = (getattr(hv[idx], "id", None), sheet)
                except Exception:
                    pass
            return action, h

        if kind == "open_version":
            if not self.versions:
                action = f"{p}.history()"
                return action, self.history_view(p)
            vname = rng.choice(sorted(self.versions))
            vid, sheet = self.versions[vname]
            ref = rng.choice(CELLS)
            text = self.pick_text()
            action = (f"{p}.open_version({vname}); set_cell({ref!r}, {text!r}, sheet={sheet!r}); "
                      f"close_version()")
            if _safe(lambda: c.open_version(vid)) == "refusé":
                return action, "refusé"
            seen = self.cell_view(c, sheet, CELLS)
            _safe(lambda: c.set_cell(ref, text, sheet=sheet))
            after = self.cell_view(c, sheet, [ref])
            closed = _safe(c.close_version)
            return action, {"version_ouverte": seen, "après_saisie": after,
                            "fermée": closed != "refusé",
                            "courant": self.cell_view(c, sheet, CELLS)}

        if kind == "restore":
            if not self.versions:
                action = f"{p}.history()"
                return action, self.history_view(p)
            vname = rng.choice(sorted(self.versions))
            vid, sheet = self.versions[vname]
            action = f"{p}.restore_version({vname}); deliver_all()"
            if _safe(lambda: c.restore_version(vid)) == "refusé":
                return action, "refusé"
            _safe(self.net.deliver_all)
            return action, {"vue": self.person_view(p, sheet),
                            "historique": self.history_view(p, sheet)}

        if kind == "export":
            action = f"{p}.export_csv()"
            try:
                data = c.export_csv()
            except Exception:
                return action, "refusé"
            if not isinstance(data, (bytes, bytearray)):
                return action, {"type_inattendu": True}
            try:
                text = bytes(data).decode("utf-8")
                import csv
                import io
                rows = list(csv.reader(io.StringIO(text, newline="")))
                return action, {"lignes": rows}
            except Exception:
                return action, {"octets": len(data), "utf8_valide": False}

        if kind == "import":
            data = rng.choice(CSVS)
            label = data.decode("utf-8", "replace")
            action = f"{p}.import_csv({label!r})"
            if _safe(lambda: c.import_csv(data)) == "refusé":
                return action, "refusé"
            sheets = self.known_sheets(c)
            return action, self.person_view(p, None if not sheets else None)

        # activate
        sheet = self.pick_sheet(p)
        action = f"{p}.activate({sheet!r})"
        if _safe(lambda: c.activate(sheet)) == "refusé":
            return action, "refusé"
        return action, {"feuilles": sorted(self.known_sheets(c))}


def scenario(app, rng, dossier):
    '''Joue une situation tirée au hasard. `app` est le module à tester, `rng` un random.Random
    déjà semé, `dossier` un dossier vide (pour ce qui doit être conservé sur disque).
    Rend une liste de paires (action, observation).'''
    n = rng.randint(15, 40)
    out = []
    try:
        sim = _Sim(app, rng)
    except Exception:
        out.append(("ouvrir_classeur(alice, bob, carol)", "refusé"))
        for i in range(n - 1):
            rng.random()
            out.append((f"action_impossible({i})", "refusé"))
        return out
    out.append(("ouvrir_classeur(alice, bob, carol)", sim.person_view("alice", "Feuille1")))
    for _ in range(n - 1):
        try:
            action, obs = sim.step()
        except Exception:
            action, obs = "action_interrompue()", "refusé"
        out.append((action, obs))
    return out
