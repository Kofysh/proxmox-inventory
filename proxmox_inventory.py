#!/usr/bin/env python3
"""Inventaire Proxmox VE en lecture seule — bibliothèque standard Python."""
from __future__ import annotations

import argparse
import errno
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import textwrap
import ssl
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

VERSION = "1.3.0"
COLOR_MODE = "auto"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class InventoryError(Exception):
    """Erreur dont le message peut être présenté sans divulguer le jeton."""


def connection_error(error):
    """Classer la cause sans exposer les messages bruts ou les secrets."""
    cause = error.reason if isinstance(error, URLError) else error
    if isinstance(cause, ssl.SSLCertVerificationError):
        detail = "certificat HTTPS non validé ; vérifier le nom DNS, la date et PVE_CA_FILE."
    elif isinstance(cause, ssl.SSLError):
        detail = "négociation TLS échouée ; vérifier le service HTTPS et sa configuration."
    elif isinstance(cause, socket.gaierror):
        detail = "résolution DNS échouée ; vérifier PVE_URL et le résolveur du poste."
    elif isinstance(cause, (TimeoutError, socket.timeout)) or getattr(cause, "errno", None) == errno.ETIMEDOUT:
        detail = "délai réseau dépassé ; vérifier le routage, le pare-feu et PVE_TIMEOUT."
    elif isinstance(cause, ConnectionRefusedError) or getattr(cause, "errno", None) == errno.ECONNREFUSED:
        detail = "connexion refusée ; vérifier le port de PVE_URL et le service à destination."
    elif getattr(cause, "errno", None) in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        detail = "réseau ou hôte inaccessible ; vérifier le VPN et le routage."
    elif isinstance(cause, (ConnectionResetError, ConnectionAbortedError, HTTPException)):
        detail = "connexion interrompue ou réponse incomplète ; réessayer et vérifier le serveur."
    else:
        detail = "vérifier réseau/VPN, DNS, port, délai et certificat HTTPS."
    return InventoryError("Connexion impossible : " + detail)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Ne jamais transmettre Authorization vers une autre destination.
        return None


class ProxmoxClient:
    """Client volontairement limité aux deux routes nécessaires."""
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.base_url = env.get("PVE_URL", "").rstrip("/")
        token_id = env.get("PVE_TOKEN_ID", "")
        secret = env.get("PVE_TOKEN_SECRET", "")
        if not all((self.base_url, token_id, secret)):
            raise InventoryError("Configurer PVE_URL, PVE_TOKEN_ID et PVE_TOKEN_SECRET.")
        try:
            url = urlsplit(self.base_url)
            port = url.port
            valid = (url.scheme == "https" and url.hostname and not url.username
                     and not url.password and not url.path and not url.query
                     and not url.fragment and (port is None or port > 0)
                     and not any(c.isspace() or ord(c) < 32 for c in self.base_url))
        except ValueError:
            valid = False
        if not valid:
            raise InventoryError("PVE_URL doit être une origine HTTPS, par exemple https://pve.example.net:8006.")
        if not token_id.isascii() or not re.fullmatch(r"[^\s@!=]+@[^\s@!=]+![^\s@!=]+", token_id):
            raise InventoryError("PVE_TOKEN_ID doit avoir la forme utilisateur@realm!nom-jeton.")
        if not re.fullmatch(r"[\x21-\x7e]+", secret):
            raise InventoryError("PVE_TOKEN_SECRET contient des caractères invalides.")
        try:
            self.timeout = float(env.get("PVE_TIMEOUT", "10"))
            if not math.isfinite(self.timeout) or not 0 < self.timeout <= 120:
                raise ValueError
        except ValueError:
            raise InventoryError("PVE_TIMEOUT doit être un nombre entre 0 (exclu) et 120 secondes.") from None
        try:
            context = ssl.create_default_context(cafile=env.get("PVE_CA_FILE") or None)
        except (OSError, ssl.SSLError):
            raise InventoryError("Impossible de charger le certificat de confiance PVE_CA_FILE.") from None
        # Pas de proxy implicite via les variables d'environnement.
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())
        self._authorization = f"PVEAPIToken={token_id}={secret}"

    def get(self, route):
        if route not in ("/nodes", "/cluster/resources?type=vm"):
            raise InventoryError("Route non autorisée par cet outil de lecture seule.")
        request = Request(self.base_url + "/api2/json" + route, method="GET", headers={
            "Authorization": self._authorization, "Accept": "application/json",
            "User-Agent": f"proxmox-inventory/{VERSION}",
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 401:
                raise InventoryError("HTTP 401 : authentification refusée ; vérifier le jeton et son expiration.") from None
            if status == 403:
                raise InventoryError("HTTP 403 : droits insuffisants ; vérifier les ACL utilisateur et jeton.") from None
            if 300 <= status < 400:
                raise InventoryError("Redirection HTTP refusée ; utiliser directement l'adresse HTTPS de l'API.") from None
            raise InventoryError(f"L'API a renvoyé HTTP {status}.") from None
        except (ssl.SSLError, URLError, TimeoutError, OSError, HTTPException) as exc:
            raise connection_error(exc) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise InventoryError("Réponse API trop volumineuse (limite : 10 Mio).")
        try:
            envelope = json.loads(raw)
        except (ValueError, UnicodeError):
            raise InventoryError("L'API n'a pas renvoyé un JSON valide.") from None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), list):
            raise InventoryError("Réponse API inattendue : liste data absente.")
        return envelope["data"]


def number(row, key, integer=False):
    value = row.get(key)
    if value is None:
        return None  # Une donnée absente n'est pas assimilée à zéro.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise InventoryError(f"Donnée API invalide : {key}.")
    if integer and int(value) != value:
        raise InventoryError(f"Donnée API invalide : {key} doit être un entier.")
    return int(value) if integer else value


def text_field(row, key, required=False):
    value = row.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise InventoryError(f"Donnée API invalide : {key}.")
    return value


def build_report(nodes, resources, mode, source):
    if not isinstance(nodes, list) or not isinstance(resources, list):
        raise InventoryError("Le jeu de données doit contenir deux listes.")
    normalized_nodes, guests, warnings = [], [], []
    for row in nodes:
        if not isinstance(row, dict):
            raise InventoryError("Entrée de nœud invalide.")
        node = {"name": text_field(row, "node", True), "status": text_field(row, "status"),
                "cpu_count": number(row, "maxcpu", True), "memory_total_bytes": number(row, "maxmem", True),
                "memory_used_bytes": number(row, "mem", True)}
        normalized_nodes.append(node)
        if node["status"] != "online":
            warnings.append(f"Nœud {node['name']} : état {node['status'] or 'inconnu'}.")
    for row in resources:
        if not isinstance(row, dict):
            raise InventoryError("Entrée de ressource invalide.")
        if row.get("type") not in ("qemu", "lxc"):
            raise InventoryError("Type de ressource inattendu pour l'inventaire des invités.")
        vmid = number(row, "vmid", True)
        if vmid is None:
            raise InventoryError("Identifiant vmid absent.")
        template = row.get("template", 0)
        if template not in (0, 1):
            raise InventoryError("Indicateur template invalide.")
        guests.append({"vmid": vmid, "name": text_field(row, "name"),
                       "node": text_field(row, "node", True), "type": row["type"],
                       "status": text_field(row, "status"), "is_template": bool(template),
                       "vcpu": number(row, "maxcpu", True),
                       "memory_allocated_bytes": number(row, "maxmem", True),
                       "disk_reported_bytes": number(row, "maxdisk", True)})
    normalized_nodes.sort(key=lambda n: n["name"])
    guests.sort(key=lambda g: (g["node"], g["vmid"]))
    workloads = [g for g in guests if not g["is_template"]]
    if not normalized_nodes:
        warnings.append("Aucun nœud visible : vérifier les ACL ; ce résultat ne prouve pas que le cluster est vide.")
    if not guests:
        warnings.append("Aucun invité visible : vérifier les ACL et le contenu du cluster.")
    warnings.append("L'inventaire est limité aux ressources visibles par le jeton ; son exhaustivité n'est pas vérifiée.")
    return {
        "schema_version": 1, "tool_version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(), "mode": mode, "source": source,
        "collection_status": "completed", "scope": "synthetic_dataset" if mode == "demo" else "resources_visible_to_token",
        "summary": {"nodes": len(normalized_nodes), "guests": len(workloads),
                    "running": sum(g["status"] == "running" for g in workloads),
                    "stopped": sum(g["status"] == "stopped" for g in workloads),
                    "other_states": sum(g["status"] not in ("running", "stopped") for g in workloads),
                    "templates": sum(g["is_template"] for g in guests)},
        "nodes": normalized_nodes, "guests": guests, "warnings": warnings,
        "limitations": ["Ce rapport ne constitue pas un audit de sécurité.",
                        "disk_reported_bytes reprend maxdisk ; ce n'est pas la somme garantie de tous les disques.",
                        "Aucune validation de Paymenter, du paiement ou du provisionnement n'est effectuée."]}


def write_report(report, output):
    """Écriture atomique : ne pas laisser un JSON partiellement écrit."""
    output = Path(output)
    temporary = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         prefix=".inventory-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, output)
    except OSError:
        raise InventoryError("Impossible d'écrire le rapport ; vérifier le chemin et les permissions.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe(value):
    # Les noms provenant de l'API ne doivent pas injecter d'échappements terminal.
    return "".join(c if c.isprintable() else "?" for c in str(value))


def gib(value):
    return "n/d" if value is None else f"{value / 1024**3:.1f} Gio"


def colorize(text, style, stream=None):
    stream = sys.stdout if stream is None else stream
    enabled = COLOR_MODE == "always" or (COLOR_MODE == "auto" and
              "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb" and
              getattr(stream, "isatty", lambda: False)())
    return f"\033[{style}m{text}\033[0m" if enabled else text


def display_date(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return safe(value)
        try:
            local = stamp.astimezone(ZoneInfo("Europe/Paris"))
            offset = local.strftime("%z")
            return local.strftime("%d/%m/%Y à %H:%M:%S") + f" (Paris, UTC{offset[:3]}:{offset[3:]})"
        except ZoneInfoNotFoundError:
            return stamp.astimezone(timezone.utc).strftime("%d/%m/%Y à %H:%M:%S UTC") + " (fuseau Paris indisponible)"
    except (ValueError, TypeError):
        return safe(value)


def count_label(count, singular, plural=None):
    return f"{count} {singular if count in (0, 1) else (plural or singular + 's')}"


def report_age(value, now=None):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return "Ancienneté indisponible : date sans fuseau."
        seconds = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
    except (ValueError, TypeError):
        return "Ancienneté indisponible."
    if seconds < 0:
        return "Date de collecte dans le futur : vérifier les horloges."
    if seconds < 60:
        return "Collecté il y a moins d’une minute."
    if seconds < 3600:
        age = count_label(int(seconds // 60), "minute")
    elif seconds < 86400:
        age = count_label(int(seconds // 3600), "heure")
    else:
        age = count_label(int(seconds // 86400), "jour")
    return "Collecté il y a " + age + "."


def terminal_width():
    return max(40, min(shutil.get_terminal_size((80, 24)).columns, 120))


def print_note(message, prefix="  "):
    wrapped = textwrap.fill(safe(message), width=terminal_width(),
                            initial_indent=prefix, subsequent_indent="  ")
    style = "32" if message.startswith("[OK]") else ("33" if prefix == "- " else "0")
    print(colorize(wrapped, style) if style != "0" else wrapped)


def print_heading(title):
    print("\n" + colorize(safe(title), "1;35"))
    print(colorize("─" * terminal_width(), "2"))


def print_table(headers, rows):
    rows = [[safe(value) for value in row] for row in rows]
    if not rows:
        print("  Aucune ressource ne correspond à la sélection.")
        return
    headers = [safe(value) for value in headers]
    widths = [min(28, max(len(title), *(len(row[i]) for row in rows)))
              for i, title in enumerate(headers)]
    available = terminal_width() - 2 * (len(headers) - 1)
    while sum(widths) > available:
        widest = max(range(len(widths)), key=widths.__getitem__)
        widths[widest] -= 1
    for index, row in enumerate([headers, *rows]):
        cells = [textwrap.wrap(value, width=width) or [""]
                 for value, width in zip(row, widths)]
        for line in range(max(map(len, cells))):
            pieces = []
            for column, (cell, width) in enumerate(zip(cells, widths)):
                text = (cell[line] if line < len(cell) else "").ljust(width)
                if column == len(cells) - 1:
                    text = text.rstrip()
                style = "1" if index == 0 else {"actif": "32", "en ligne": "32",
                    "arrêté": "33", "hors ligne": "31", "inconnu": "33", "modèle": "35"}.get(row[column].casefold())
                pieces.append(colorize(text, style) if style else text)
            print("  ".join(pieces).rstrip())
        if index == 0:
            print(colorize("  ".join("─" * width for width in widths), "2"))


def display_status(value):
    return {"online": "En ligne", "offline": "Hors ligne", "running": "Actif",
            "stopped": "Arrêté", None: "Inconnu"}.get(value, value)


def print_summary(report, node=None, status=None):
    print_heading("Proxmox Inventory")
    print_note("Lecture seule | " + display_date(report["generated_at"]))
    if report["mode"] != "demo":
        print_note(report_age(report["generated_at"]))
    if report["mode"] == "demo":
        print_note("Données fictives — aucune connexion à un serveur.")
    s = report["summary"]
    print_heading("Vue d’ensemble")
    print_note(" • ".join(count_label(s[key], label) for key, label in
                          (("nodes", "Nœud"), ("guests", "Invité"), ("templates", "Modèle"))))
    print_note(" • ".join(count_label(s[key], label) for key, label in
                          (("running", "Actif"), ("stopped", "Arrêté"), ("other_states", "Autre"))))
    nodes = [n for n in report["nodes"] if node is None or n["name"] == node]
    guests = [g for g in report["guests"] if (node is None or g["node"] == node)
              and (status is None or g["status"] == status)]
    if node or status:
        print_note("Filtres : Nœud = " + (node or "Tous") + " ; État = " + (display_status(status) if status else "Tous"))
        print_note("Le JSON conserve l’inventaire complet.")
    print_heading("Nœuds")
    print_table(["Nœud", "État", "CPU", "RAM utilisée", "RAM totale"], [
        [n["name"], display_status(n["status"]), n["cpu_count"] if n["cpu_count"] is not None else "n/d",
         gib(n["memory_used_bytes"]), gib(n["memory_total_bytes"])] for n in nodes])
    for name in sorted({g["node"] for g in guests}):
        print_heading("Invités / " + safe(name))
        print_table(["ID", "Type", "Nom", "État", "vCPU", "RAM", "Disque*"], [
            [g["vmid"], g["type"].upper(), g["name"] or "n/d",
             "Modèle" if g["is_template"] else display_status(g["status"]),
             g["vcpu"] if g["vcpu"] is not None else "n/d",
             gib(g["memory_allocated_bytes"]), gib(g["disk_reported_bytes"])]
            for g in guests if g["node"] == name])
    if not guests:
        print_heading("Invités")
        print("  Aucune ressource ne correspond à la sélection.")
    print_heading("Notes")
    print_note("* Disque déclaré par l’API (maxdisk), pas nécessairement le total des disques.")
    for warning in report["warnings"]:
        print_note(warning, "- ")


def read_inventory(path):
    """Charge uniquement les rapports complets compatibles avec le schéma v1."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise InventoryError("Rapport trop volumineux (limite : 10 Mio).")
        report = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise InventoryError("Impossible de lire l’un des inventaires JSON.") from None
    validate_inventory(report)
    return report


def validate_inventory(report):
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise InventoryError("Schéma d’inventaire non pris en charge (version 1 attendue).")
    mode = report.get("mode")
    if mode not in ("demo", "live") or report.get("collection_status") != "completed":
        raise InventoryError("La comparaison exige deux inventaires terminés.")
    expected_scope = "synthetic_dataset" if mode == "demo" else "resources_visible_to_token"
    if report.get("scope") != expected_scope or report.get("filters"):
        raise InventoryError("La comparaison exige des inventaires complets, sans filtrage.")
    text_field(report, "source", True)
    try:
        stamp = datetime.fromisoformat(text_field(report, "generated_at", True))
        if stamp.tzinfo is None:
            raise ValueError
    except ValueError:
        raise InventoryError("Horodatage d’inventaire invalide ou sans fuseau horaire.") from None
    for collection in ("nodes", "guests"):
        rows = report.get(collection)
        if not isinstance(rows, list):
            raise InventoryError("Liste de ressources absente dans l’inventaire.")
        identities = set()
        for row in rows:
            if not isinstance(row, dict):
                raise InventoryError("Ressource invalide dans l’inventaire.")
            if collection == "nodes":
                identity = text_field(row, "name", True)
                text_field(row, "status")
                for field in ("cpu_count", "memory_total_bytes", "memory_used_bytes"):
                    number(row, field, True)
            else:
                identity = number(row, "vmid", True)
                if identity is None or row.get("type") not in ("qemu", "lxc") or type(row.get("is_template")) is not bool:
                    raise InventoryError("Identité d’invité invalide dans l’inventaire.")
                text_field(row, "node", True)
                text_field(row, "name")
                text_field(row, "status")
                for field in ("vcpu", "memory_allocated_bytes", "disk_reported_bytes"):
                    number(row, field, True)
            if identity in identities:
                raise InventoryError("Identité de ressource dupliquée dans l’inventaire.")
            identities.add(identity)


def compare_inventories(before, after):
    for report in (before, after):
        validate_inventory(report)
    if (before["mode"], before["source"]) != (after["mode"], after["source"]):
        raise InventoryError("Les deux inventaires doivent provenir de la même source et du même mode.")
    if datetime.fromisoformat(before["generated_at"]) > datetime.fromisoformat(after["generated_at"]):
        raise InventoryError("Le premier inventaire doit être antérieur ou égal au second.")
    result = {"schema_version": 1, "report_type": "comparison", "tool_version": VERSION,
              "generated_at": datetime.now(timezone.utc).isoformat(), "mode": after["mode"],
              "source": after["source"], "before_at": before["generated_at"], "after_at": after["generated_at"],
              "warnings": ["Une ressource absente peut être masquée par les droits du jeton ; son absence ne prouve pas sa suppression.",
                           "Un VMID réutilisé ne permet pas de distinguer une recréation d’une modification."]}
    fields = {"nodes": ("status", "cpu_count", "memory_total_bytes"),
              "guests": ("name", "node", "type", "status", "is_template", "vcpu",
                         "memory_allocated_bytes", "disk_reported_bytes")}
    for kind, tracked in fields.items():
        identity = "name" if kind == "nodes" else "vmid"
        old = {r[identity]: r for r in before[kind]}
        new = {r[identity]: r for r in after[kind]}
        changes = []
        for key in sorted(old.keys() & new.keys()):
            changed = {f: {"before": old[key].get(f), "after": new[key].get(f)}
                       for f in tracked if old[key].get(f) != new[key].get(f)}
            if changed:
                changes.append({identity: key, "changes": changed})
        result[kind] = {"added": [new[k] for k in sorted(new.keys() - old.keys())],
                        "removed": [old[k] for k in sorted(old.keys() - new.keys())], "changed": changes}
    result["has_changes"] = any(result[k][category] for k in fields for category in ("added", "removed", "changed"))
    return result


def print_comparison(report):
    print_heading("Comparaison d’inventaires / " + ("Démonstration" if report["mode"] == "demo" else "Collecte réelle"))
    print_note("Avant : " + display_date(report["before_at"]))
    print_note("Après : " + display_date(report["after_at"]))
    print_heading("Bilan")
    print_table(["Ressources", "Visibles +", "Absentes", "Modifiées"], [
        [label, len(report[kind]["added"]), len(report[kind]["removed"]), len(report[kind]["changed"])]
        for kind, label in (("nodes", "Nœuds"), ("guests", "Invités"))])
    labels = {"status": "État", "cpu_count": "CPU", "memory_total_bytes": "RAM totale",
              "name": "Nom", "node": "Nœud", "type": "Type", "is_template": "Modèle",
              "vcpu": "vCPU", "memory_allocated_bytes": "RAM", "disk_reported_bytes": "Disque"}
    def value(field, item):
        if field.endswith("_bytes"):
            return gib(item)
        if field == "is_template":
            return "oui" if item else "non"
        if field == "status":
            return display_status(item)
        return "n/d" if item is None else item
    for kind, label in (("nodes", "Nœuds"), ("guests", "Invités")):
        delta = report[kind]
        if not any(delta.values()):
            continue
        print_heading(label)
        key = "name" if kind == "nodes" else "vmid"
        for category, title in (("added", "Nouvellement visible"), ("removed", "Absent")):
            for row in delta[category]:
                print_note(title + " : " + str(row[key]))
        rows = [[row[key], labels.get(field, field), value(field, values["before"]), value(field, values["after"])]
                for row in delta["changed"] for field, values in row["changes"].items()]
        if rows:
            print_table(["Ressource", "Champ", "Avant", "Après"], rows)
    if not report["has_changes"]:
        print_note("Aucun changement sur les champs suivis.")
    print_heading("Notes")
    for warning in report["warnings"]:
        print_note(warning, "- ")


def save_history(report, directory):
    """Publier ensemble inventaire et comparaison, sans écraser une collecte."""
    validate_inventory(report)
    root = Path(directory)
    lock = root / ".inventory.lock"
    acquired = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise InventoryError("Historique verrouillé : une autre collecte écrit peut-être dans ce dossier. "
                                 "Si elle a été interrompue, vérifier son arrêt avant de retirer .inventory.lock.") from None
        acquired = True
        os.close(descriptor)
        previous = sorted(path for path in root.glob("run-*") if path.is_dir())
        comparison = None
        if previous:
            before = read_inventory(previous[-1] / "inventory.json")
            comparison = compare_inventories(before, report)
        stamp = datetime.fromisoformat(report["generated_at"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = root / ("run-" + stamp + "-" + uuid.uuid4().hex)
        # Le dossier final ne devient visible qu’une fois tous ses JSON écrits.
        with tempfile.TemporaryDirectory(prefix=".pending-", dir=root) as staging:
            stage = Path(staging)
            write_report(report, stage / "inventory.json")
            if comparison is not None:
                write_report(comparison, stage / "comparison.json")
            stage.rename(destination)
        return destination, comparison
    except OSError:
        raise InventoryError("Impossible d’enregistrer l’historique ; vérifier le chemin, l’espace et les permissions.") from None
    finally:
        if acquired:
            lock.unlink(missing_ok=True)


def check_connection(quiet=False):
    """Diagnostic avec les mêmes requêtes et contrôles que la collecte."""
    if not quiet:
        print_heading("Proxmox Inventory")
        print_note("Diagnostic de connexion")
    stage = "Configuration"
    try:
        client = ProxmoxClient()
        if not quiet:
            print_note("[OK] Configuration et autorité de confiance chargées.")
        stage = "API des nœuds"
        nodes = client.get("/nodes")
        if not quiet:
            print_note("[OK] HTTPS vérifié, réponse reçue pour /nodes.")
        stage = "API des invités"
        resources = client.get("/cluster/resources?type=vm")
        if not quiet:
            print_note("[OK] Réponse reçue pour /cluster/resources?type=vm.")
        stage = "Validation des données"
        report = build_report(nodes, resources, "live", client.base_url)
        validate_inventory(report)
    except InventoryError as exc:
        raise InventoryError(stage + " : " + str(exc)) from None
    if not quiet:
        print_note("[OK] Données valides ; aucun fichier créé.")
        print_heading("Visibilité")
        summary = report["summary"]
        print_note(", ".join(count_label(summary[key], label) for key, label in
                             (("nodes", "Nœud"), ("guests", "Invité"), ("templates", "Modèle"))))
        for warning in report["warnings"]:
            print_note(warning, "- ")
    return 0


def main(argv=None):
    global COLOR_MODE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="Couleurs du terminal : auto (défaut), always ou never. Respecte NO_COLOR en mode auto.")
    parser.add_argument("--history", nargs="?", const="reports/history", metavar="DOSSIER",
                        help="Conserver une collecte datée et la comparer à la précédente (défaut : reports/history).")
    parser.add_argument("--check", action="store_true", help="Diagnostiquer la connexion et les données API, sans écrire de rapport.")
    parser.add_argument("--quiet", action="store_true", help="Afficher uniquement les erreurs ; conserve les exports et les codes de retour.")
    parser.add_argument("--demo", action="store_true", help="Données fictives locales, sans réseau ni jeton.")
    parser.add_argument("--output", help="Destination JSON ; par défaut reports/inventory.json ou reports/comparison.json.")
    parser.add_argument("--compare", nargs=2, metavar=("AVANT", "APRES"), help="Comparer deux rapports locaux, sans réseau.")
    parser.add_argument("--node", help="Filtrer le résumé du terminal par nom de nœud.")
    parser.add_argument("--status", choices=("running", "stopped"), help="Filtrer les invités affichés par état.")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    COLOR_MODE = args.color
    if args.compare and (args.demo or args.node or args.status):
        parser.error("--compare ne se combine pas avec --demo, --node ou --status.")
    if args.history is not None and (args.output or args.compare or args.check):
        parser.error("--history ne se combine pas avec --output, --compare ou --check.")
    if args.check and (args.demo or args.compare or args.node or args.status or args.output):
        parser.error("--check accepte uniquement --quiet et --color comme options supplémentaires.")
    try:
        if args.check:
            return check_connection(args.quiet)
        if args.compare:
            output = args.output or "reports/comparison.json"
            if any(Path(output).resolve() == Path(p).resolve() for p in args.compare):
                raise InventoryError("La destination ne doit pas écraser un inventaire comparé.")
            comparison = compare_inventories(*(read_inventory(p) for p in args.compare))
            write_report(comparison, output)
            if not args.quiet:
                print_comparison(comparison)
                print_heading("Export")
                print_note("JSON : " + str(output))
            return 0
        if args.demo:
            try:
                fixture = json.loads((Path(__file__).parent / "examples/demo_api.json").read_text(encoding="utf-8"))
                nodes, resources = fixture["nodes"], fixture["resources"]
            except (OSError, ValueError, KeyError, TypeError):
                raise InventoryError("Jeu de démonstration absent ou invalide.") from None
            mode, source = "demo", "jeu de données fictif local"
        else:
            client = ProxmoxClient()
            nodes = client.get("/nodes")
            resources = client.get("/cluster/resources?type=vm")
            mode, source = "live", client.base_url
        report = build_report(nodes, resources, mode, source)
        if args.history is not None:
            folder, comparison = save_history(report, args.history)
            if not args.quiet:
                print_summary(report, args.node, args.status)
                if comparison is not None:
                    print_comparison(comparison)
                else:
                    print_heading("Historique")
                    print_note("Première collecte : référence enregistrée pour la prochaine comparaison.")
                print_heading("Export")
                print_note("Inventaire : " + str(folder / "inventory.json"))
                if comparison is not None:
                    print_note("Comparaison : " + str(folder / "comparison.json"))
            return 0
        output = args.output or "reports/inventory.json"
        write_report(report, output)
        if not args.quiet:
            print_summary(report, args.node, args.status)
            print_heading("Export")
            print_note("JSON : " + str(output))
        return 0
    except InventoryError as exc:
        print(colorize("Erreur : " + str(exc), "31", sys.stderr), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interruption utilisateur.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
