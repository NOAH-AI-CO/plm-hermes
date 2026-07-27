#!/usr/bin/env python3
"""
Stage 2.5: Cross-page edge resolution.

Scans terminal nodes (is_end=True, 0 outgoing edges) whose title contains a
reference to another page code (e.g. "Treatment Induction (APL-2)").  Creates
real edge_rules from that node to the target page's entry nodes, plus
page_links when missing.  Also back-fills orphan care_phase_id assignments.

This is deterministic — no LLM calls.  Safe to re-run (idempotent: skips
edges/links that already exist).

Usage (standalone):
    cd noah_agent
    python -m agent.patient_like_me.v1.indexing.resolve_cross_page_edges [guideline_id]
"""
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[3]


def resolve_cross_page_edges(guideline_id: int) -> dict:
    """
    Create explicit cross-page edge_rules for terminal flowchart nodes that
    reference another page in their title, and fix orphan care_phase_id.

    Operates on the raw ES document in a single read-modify-write cycle for
    efficiency (avoids per-edge _scan_all_guidelines overhead).
    """
    from agent.patient_like_me.v1.guideline import guidance_db

    doc = guidance_db.get_guideline_doc(guideline_id)
    if not doc:
        return {"error": f"guideline {guideline_id} not found"}

    nodes = doc.get("nodes", [])
    edge_rules = doc.get("edge_rules", [])
    pages = doc.get("pages", [])
    page_links = doc.setdefault("page_links", [])

    # --- build indexes -------------------------------------------------------
    page_code_to_id: dict[str, int] = {}
    page_id_to_code: dict[int, str] = {}
    for p in pages:
        code = (p.get("code") or "").strip()
        if code:
            canonical = _normalise_page_code(code)
            page_code_to_id[canonical] = p["id"]
            page_id_to_code[p["id"]] = code

    node_by_id = {n["id"]: n for n in nodes}
    entry_by_pid: dict[int, list[int]] = defaultdict(list)
    all_nodes_by_pid: dict[int, list[int]] = defaultdict(list)
    for n in nodes:
        all_nodes_by_pid[n["page_id"]].append(n["id"])
        if n.get("is_entry"):
            entry_by_pid[n["page_id"]].append(n["id"])

    out_deg: dict[int, int] = defaultdict(int)
    existing_edge_set: set[tuple[int, int]] = set()
    for e in edge_rules:
        out_deg[e["source_node_id"]] += 1
        existing_edge_set.add((e["source_node_id"], e["target_node_id"]))

    existing_link_set = {
        (l["source_page_id"], l["target_page_id"]) for l in page_links
    }

    next_id = doc.get("next_id", 1)
    new_edges = 0
    new_links = 0

    # --- (A) terminal nodes with page-code references in title ---------------
    for n in nodes:
        if not n.get("is_end") or out_deg.get(n["id"], 0) > 0:
            continue

        title = n.get("title", "")
        source_page_id = n["page_id"]

        codes_found = _extract_page_codes_from_title(title, page_code_to_id)
        for target_code in codes_found:
            target_page_id = page_code_to_id[target_code]
            if target_page_id == source_page_id:
                continue

            # page_link
            lk = (source_page_id, target_page_id)
            if lk not in existing_link_set:
                page_links.append({
                    "id": next_id,
                    "source_page_id": source_page_id,
                    "target_page_id": target_page_id,
                    "created_at": datetime.now().isoformat(),
                })
                next_id += 1
                existing_link_set.add(lk)
                new_links += 1
                src_code = page_id_to_code.get(source_page_id, str(source_page_id))
                print(f"  [2.5] page_link: {src_code}({source_page_id}) → {target_code}({target_page_id})")

            # edge_rules to target page entry nodes
            target_entries = entry_by_pid.get(target_page_id) or all_nodes_by_pid.get(target_page_id, [])
            for tgt_nid in target_entries:
                if (n["id"], tgt_nid) in existing_edge_set:
                    continue
                edge_rules.append({
                    "id": next_id,
                    "source_node_id": n["id"],
                    "target_node_id": tgt_nid,
                    "rule_text": f"Proceed to {target_code}",
                    "relation_type": "sequence",
                    "priority": 0,
                    "rule_signature": "",
                    "source_page_number": None,
                    "rule_status": "draft",
                    "condition_expr": {},
                    "created_at": datetime.now().isoformat(),
                })
                next_id += 1
                existing_edge_set.add((n["id"], tgt_nid))
                out_deg[n["id"]] += 1
                new_edges += 1

            if target_entries:
                print(f"  [2.5] edges: N{n['id']} ({title[:50]}) → {len(target_entries)} entry nodes on {target_code}")

    # --- (B) dead-end entry pages → next sequential page -----------------------
    # Handles patterns like BPDCN-INTRO → BPDCN-1, where an intro/content page
    # is reachable but has no forward link to the actual flowchart.
    page_type_by_id = {p["id"]: (p.get("page_type") or "").strip().lower() for p in pages}
    dead_end_linked = 0

    for p in pages:
        pid = p["id"]
        code = (p.get("code") or "").strip()
        if not code:
            continue
        page_node_ids = all_nodes_by_pid.get(pid, [])
        if not page_node_ids:
            continue
        if any(out_deg.get(nid, 0) > 0 for nid in page_node_ids):
            continue

        canonical = _normalise_page_code(code)
        next_candidates = []
        if canonical.endswith("-INTRO"):
            base = canonical.rsplit("-INTRO", 1)[0]
            next_candidates.append(f"{base}-1")
        m = re.match(r"^(.+-)(\d+)$", canonical)
        if m:
            next_candidates.append(f"{m.group(1)}{int(m.group(2)) + 1}")

        for next_code in next_candidates:
            if next_code not in page_code_to_id:
                continue
            target_pid = page_code_to_id[next_code]
            if target_pid == pid:
                continue

            lk = (pid, target_pid)
            if lk not in existing_link_set:
                page_links.append({
                    "id": next_id,
                    "source_page_id": pid,
                    "target_page_id": target_pid,
                    "created_at": datetime.now().isoformat(),
                })
                next_id += 1
                existing_link_set.add(lk)
                new_links += 1
                print(f"  [2.5] page_link (dead-end): {code}({pid}) → {next_code}({target_pid})")

            target_entries = entry_by_pid.get(target_pid) or all_nodes_by_pid.get(target_pid, [])
            for src_nid in page_node_ids:
                for tgt_nid in target_entries:
                    if (src_nid, tgt_nid) in existing_edge_set:
                        continue
                    edge_rules.append({
                        "id": next_id,
                        "source_node_id": src_nid,
                        "target_node_id": tgt_nid,
                        "rule_text": f"Proceed to {next_code}",
                        "relation_type": "sequence",
                        "priority": 0,
                        "rule_signature": "",
                        "source_page_number": None,
                        "rule_status": "draft",
                        "condition_expr": {},
                        "created_at": datetime.now().isoformat(),
                    })
                    next_id += 1
                    existing_edge_set.add((src_nid, tgt_nid))
                    out_deg[src_nid] += 1
                    new_edges += 1
                    dead_end_linked += 1

            if target_entries:
                print(f"  [2.5] dead-end edges: {code} → {len(page_node_ids)}×{len(target_entries)} edges to {next_code}")
            break

    if dead_end_linked:
        print(f"  [2.5] Dead-end pages linked: {dead_end_linked} new edges")

    # --- (C) node content "see PAGE-CODE" references → reference edges --------
    # Scans every node's title + content for page code mentions (e.g.
    # "see AML-B", "Screening LP, see AML-B", "(AML-B)").  Creates a
    # reference edge from that specific node to the target page's entry nodes.
    see_ref_edges = 0
    _SEE_RE = re.compile(
        r"(?:see|See|SEE|见|参见|详见)\s+"
        r"([A-Z][A-Z0-9]*-[A-Z0-9]+(?:\s+\d+(?:\s+of\s+\d+)?)?)(?:\s|[),.<]|$)",
        re.IGNORECASE,
    )
    _PAREN_CODE_RE = re.compile(
        r"\(([A-Z][A-Z0-9]*-[A-Z0-9]+(?:\s+\d+(?:\s+of\s+\d+)?)?)\)",
        re.IGNORECASE,
    )

    for n in nodes:
        nid = n["id"]
        source_pid = n["page_id"]
        text = (n.get("title") or "") + " " + (n.get("content") or "")
        if not text.strip():
            continue

        found_codes: set[str] = set()
        for m in _SEE_RE.finditer(text):
            candidate = _normalise_page_code(m.group(1))
            if candidate in page_code_to_id:
                found_codes.add(candidate)
        for m in _PAREN_CODE_RE.finditer(text):
            candidate = _normalise_page_code(m.group(1))
            if candidate in page_code_to_id:
                found_codes.add(candidate)

        for target_code in found_codes:
            target_pid = page_code_to_id[target_code]
            if target_pid == source_pid:
                continue

            # page_link
            lk = (source_pid, target_pid)
            if lk not in existing_link_set:
                page_links.append({
                    "id": next_id,
                    "source_page_id": source_pid,
                    "target_page_id": target_pid,
                    "created_at": datetime.now().isoformat(),
                })
                next_id += 1
                existing_link_set.add(lk)
                new_links += 1

            target_entries = entry_by_pid.get(target_pid) or all_nodes_by_pid.get(target_pid, [])
            for tgt_nid in target_entries:
                if (nid, tgt_nid) in existing_edge_set:
                    continue
                edge_rules.append({
                    "id": next_id,
                    "source_node_id": nid,
                    "target_node_id": tgt_nid,
                    "rule_text": f"See {target_code} (Supportive Care / Reference)",
                    "relation_type": "reference",
                    "priority": 0,
                    "rule_signature": "",
                    "source_page_number": None,
                    "rule_status": "draft",
                    "condition_expr": {},
                    "created_at": datetime.now().isoformat(),
                })
                next_id += 1
                existing_edge_set.add((nid, tgt_nid))
                out_deg[nid] += 1
                new_edges += 1
                see_ref_edges += 1

        if found_codes:
            src_code = page_id_to_code.get(source_pid, str(source_pid))
            print(f"  [2.5] see-ref: N{nid} @{src_code} → {found_codes}")

    if see_ref_edges:
        print(f"  [2.5] See-reference edges: {see_ref_edges} new edges")

    # --- (D) fix orphan care_phase_id ----------------------------------------
    orphan_fixed = 0
    page_code_prefix = {}
    for pid, code in page_id_to_code.items():
        prefix = re.split(r"[\s-]+\d", code, maxsplit=1)[0].strip().upper()
        page_code_prefix[pid] = prefix

    for n in nodes:
        if n.get("care_phase_id") is not None:
            continue

        pid = n["page_id"]
        # try siblings on the same page
        sibling_phases = [
            node_by_id[nid]["care_phase_id"]
            for nid in all_nodes_by_pid.get(pid, [])
            if node_by_id[nid].get("care_phase_id") is not None and nid != n["id"]
        ]
        if sibling_phases:
            n["care_phase_id"] = Counter(sibling_phases).most_common(1)[0][0]
            orphan_fixed += 1
            continue

        # try pages with the same code prefix
        prefix = page_code_prefix.get(pid, "")
        if not prefix:
            continue
        related_phases = []
        for other_pid, other_prefix in page_code_prefix.items():
            if other_prefix == prefix and other_pid != pid:
                for nid in all_nodes_by_pid.get(other_pid, []):
                    cp = node_by_id[nid].get("care_phase_id")
                    if cp is not None:
                        related_phases.append(cp)
        if related_phases:
            n["care_phase_id"] = Counter(related_phases).most_common(1)[0][0]
            orphan_fixed += 1

    if orphan_fixed:
        print(f"  [2.5] Fixed {orphan_fixed} nodes with missing care_phase_id")

    # --- save ----------------------------------------------------------------
    doc["next_id"] = next_id
    doc["edge_rules"] = edge_rules
    doc["page_links"] = page_links
    guidance_db.save_guideline_doc(guideline_id, doc)

    stats = {
        "new_edges": new_edges,
        "new_page_links": new_links,
        "care_phase_fixed": orphan_fixed,
    }
    print(f"  [Stage 2.5] Done: {stats}")
    return stats


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_PAGE_CODE_RE = re.compile(
    r"[A-Z][A-Z0-9]*-[A-Z0-9]+(?:-[A-Z0-9]+)*",
    re.IGNORECASE,
)


def _normalise_page_code(raw: str) -> str:
    """Strip 'X of Y' suffixes and uppercase for matching."""
    upper = raw.strip().upper()
    return re.sub(r"\s+\d+\s+OF\s+\d+$", "", upper, flags=re.IGNORECASE).strip()


def _extract_page_codes_from_title(
    title: str,
    valid_codes: dict[str, int],
) -> list[str]:
    """Return page codes found inside parentheses in *title* that exist in *valid_codes*."""
    results: list[str] = []
    for m in re.finditer(r"\(([^)]+)\)", title):
        candidate = _normalise_page_code(m.group(1))
        if candidate in valid_codes:
            results.append(candidate)
    if not results:
        for m in _PAGE_CODE_RE.finditer(title):
            candidate = _normalise_page_code(m.group(0))
            if candidate in valid_codes:
                results.append(candidate)
    return results


# ---------------------------------------------------------------------------
# standalone entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        _gcp = _NOAH_AGENT_ROOT / "gcp_key.json"
        if _gcp.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp)
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "noahai-440408")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

    if str(_NOAH_AGENT_ROOT) not in sys.path:
        sys.path.insert(0, str(_NOAH_AGENT_ROOT))

    gid = int(sys.argv[1]) if len(sys.argv) > 1 else 1096994567835883201
    print(f"Running Stage 2.5 for guideline_id={gid}")
    result = resolve_cross_page_edges(gid)
    print(f"\nResult: {result}")
