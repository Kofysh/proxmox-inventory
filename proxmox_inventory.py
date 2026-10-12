#!/usr/bin/env python3
"""Inventaire Proxmox VE en lecture seule — bibliothèque standard Python."""
from __future__ import annotations

import argparse
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

VERSION = "1.0.0"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class InventoryError(Exception):
    """Erreur dont le message peut être présenté sans divulguer le jeton."""


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
        except (ssl.SSLError, URLError, TimeoutError, OSError, HTTPException):
            raise InventoryError("Connexion impossible : vérifier réseau/VPN, DNS, port, délai et certificat HTTPS.") from None
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


def print_summary(report):
    print(f"PROXMOX INVENTORY | {report['mode'].upper()} | lecture seule")
    if report["mode"] == "demo":
        print("DONNÉES FICTIVES — aucune connexion à un serveur.")
    s = report["summary"]
    print(f"{s['nodes']} nœud(s) | {s['guests']} invité(s) | {s['running']} actif(s) | "
          f"{s['stopped']} arrêté(s) | {s['templates']} modèle(s)")
    print("\nVMID | TYPE | NOM | NŒUD | ÉTAT | vCPU | RAM attribuée | DISQUE déclaré")
    for guest in report["guests"]:
        print(" | ".join(safe(v) for v in [guest["vmid"], guest["type"], guest["name"] or "n/d",
              guest["node"], "modèle" if guest["is_template"] else (guest["status"] or "inconnu"),
              guest["vcpu"] if guest["vcpu"] is not None else "n/d",
              gib(guest["memory_allocated_bytes"]), gib(guest["disk_reported_bytes"])]))
    for warning in report["warnings"]:
        print("NOTE : " + safe(warning))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Données fictives locales, sans réseau ni jeton.")
    parser.add_argument("--output", default="reports/inventory.json", help="Rapport JSON (écriture atomique).")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    try:
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
        write_report(report, args.output)
        print_summary(report)
        print("\nRapport JSON : " + safe(args.output))
        return 0
    except InventoryError as exc:
        print("ERREUR : " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interruption utilisateur.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
