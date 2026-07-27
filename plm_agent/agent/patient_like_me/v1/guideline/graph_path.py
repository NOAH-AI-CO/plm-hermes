"""
Pruned decision tree builder + Mermaid serializer for PLM graph path visualization.

Given graph structures (node_by_id, out_adj) and matched nodes from search.py,
builds a pruned tree showing the clinical decision path from root to matched nodes.

Navigational artifacts (page titles, page codes, "→ next page" edges, "See XXX"
reference edges) are collapsed so the output shows only clinical decision logic:
  patient info → NCCN decision criteria → patient's current position.
"""
from __future__ import annotations

import re
from collections import defaultdict


_PAGE_CODE_RE = re.compile(
    r"^[A-Z][A-Z0-9]*-[A-Z0-9]+(?:\s+\d+(?:\s+of\s+\d+)?)?$",
    re.IGNORECASE,
)

_PAGE_CODE_PAREN_RE = re.compile(
    r"\s*\([A-Z][A-Z0-9]*-[A-Z0-9]+(?:\s+\d+(?:\s+of\s+\d+)?)?\)",
    re.IGNORECASE,
)


def _normalise_code(raw: str) -> str:
    return re.sub(r"\s+\d+\s+OF\s+\d+$", "", raw.strip(), flags=re.IGNORECASE).strip().upper()


def _is_navigational_node(title: str, page_codes: set[str]) -> bool:
    t = title.strip()
    if not t:
        return True
    upper = t.upper()
    if upper in page_codes or _normalise_code(t) in page_codes:
        return True
    if _PAGE_CODE_RE.match(t):
        base = _normalise_code(t)
        if base in page_codes:
            return True
    if upper.startswith("NCCN GUIDELINES"):
        return True
    return False


def _is_navigational_edge(label: str, page_codes: set[str]) -> bool:
    l = label.strip()
    low = l.lower()
    if low.startswith("→ next page") or low.startswith("cross_page:"):
        return True
    m = re.match(r"(?:proceed to|see)\s+(.+?)(?:\s*\(|$)", l, re.IGNORECASE)
    if m:
        candidate = _normalise_code(m.group(1))
        if candidate in page_codes:
            return True
    return False


def _is_heuristic_edge(label: str, page_codes: set[str]) -> bool:
    """Stricter than _is_navigational_edge: only pure fallback/reference edges.

    "Proceed to APL-3" is navigational for *display* but connects real clinical
    nodes, so it's NOT heuristic.  "→ next page", "cross_page:", and
    "See PAGE-CODE ..." ARE heuristic — they're structural cross-references
    from Stage 2.5, not real clinical transitions.
    """
    l = label.strip()
    low = l.lower()
    if low.startswith("→ next page") or low.startswith("cross_page:"):
        return True
    m = re.match(r"(?:see)\s+(.+?)(?:\s*\(|$)", l, re.IGNORECASE)
    if m:
        text = m.group(1).strip()
        if text.upper().startswith("NCCN GUIDELINES"):
            return True
        candidate = _normalise_code(text)
        if candidate in page_codes:
            return True
    return False


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _clean_display_title(title: str, page_codes: set[str]) -> str:
    """Strip page-code parentheticals from node titles for display."""
    cleaned = _PAGE_CODE_PAREN_RE.sub("", title).strip()
    return cleaned if cleaned else title.strip()


def _clean_display_edge(label: str, page_codes: set[str]) -> str:
    """Strip navigational prefixes and page-code refs from edge labels."""
    l = label.strip()
    if re.match(r"See\s+\S+.*\(Supportive Care", l, re.IGNORECASE):
        return ""
    l = re.sub(r"^(?:Proceed to|Proceed with|See)\s+", "", l, flags=re.IGNORECASE)
    l = _PAGE_CODE_PAREN_RE.sub("", l).strip()
    upper = l.upper()
    if upper in page_codes or _normalise_code(l) in page_codes:
        return ""
    if _PAGE_CODE_RE.match(l):
        return ""
    if upper.startswith("NCCN GUIDELINES"):
        return ""
    return l


def build_pruned_tree(
    node_by_id: dict[int, dict],
    out_adj: dict[int, list[tuple[int, str]]],
    matched_node_ids: list[int],
    compact_paths: list[dict],
    page_codes: set[str] | None = None,
) -> dict:
    matched_set = set(matched_node_ids)
    if not matched_set:
        return {
            "nodes": {},
            "edges": [],
            "on_path_node_ids": [],
            "matched_node_ids": [],
            "sibling_node_ids": [],
        }

    _pc = page_codes or set()

    # --- step 1: collect raw on-path nodes and edges from compact_paths ------
    raw_on_path: set[int] = set()
    raw_edges: set[tuple[int, int, str]] = set()

    for cp in compact_paths:
        if cp["target_node_id"] not in matched_set:
            continue
        route = cp["route"]
        for i, step in enumerate(route):
            nid = step["node_id"]
            raw_on_path.add(nid)
            if i + 1 < len(route):
                next_nid = route[i + 1]["node_id"]
                edge_label = step["via"]
                raw_edges.add((nid, next_nid, edge_label))

    # --- step 2: collapse navigational nodes ---------------------------------
    on_path = set(raw_on_path)
    edges_list = list(raw_edges)

    if _pc:
        nav_nodes = set()
        for nid in on_path - matched_set:
            title = node_by_id.get(nid, {}).get("title", "")
            if _is_navigational_node(title, _pc):
                nav_nodes.add(nid)

        if nav_nodes:
            out_map: dict[int, list[tuple[int, str]]] = defaultdict(list)
            in_map: dict[int, list[tuple[int, str]]] = defaultdict(list)
            for s, t, l in edges_list:
                out_map[s].append((t, l))
                in_map[t].append((s, l))

            for nid in nav_nodes:
                parents = in_map.get(nid, [])
                children = out_map.get(nid, [])
                for parent_id, p_label in parents:
                    for child_id, c_label in children:
                        if child_id in nav_nodes and child_id != nid:
                            continue
                        if _is_navigational_edge(p_label, _pc):
                            label = c_label
                        else:
                            label = p_label
                        new_edge = (parent_id, child_id, label)
                        edges_list.append(new_edge)
                        out_map[parent_id].append((child_id, label))
                        in_map[child_id].append((parent_id, label))

                on_path.discard(nid)

            edges_list = [
                (s, t, l) for s, t, l in edges_list
                if s not in nav_nodes and t not in nav_nodes
            ]

    # --- step 2c: collapse reference-edge detours ----------------------------
    # When the LLM path traverses "See PAGE-CODE" reference edges between
    # treatment regimens (e.g. N611 →See→ N614 →See→ N606), those
    # intermediate hops aren't real clinical decisions.  Remove nodes whose
    # only forward on-path connection is via heuristic reference edges AND
    # that don't directly connect to a matched node, then reconnect orphaned
    # downstream nodes via direct edges from out_adj.
    if _pc:
        changed = True
        while changed:
            changed = False
            detour_nodes = set()
            for nid in on_path - matched_set:
                fwd = [(t, l) for s, t, l in edges_list
                       if s == nid and t in on_path]
                if not fwd:
                    continue
                if any(t in matched_set for t, _ in fwd):
                    continue
                if all(_is_heuristic_edge(l, _pc) for _, l in fwd):
                    detour_nodes.add(nid)

            if detour_nodes:
                on_path -= detour_nodes
                edges_list = [
                    (s, t, l) for s, t, l in edges_list
                    if s not in detour_nodes and t not in detour_nodes
                ]
                changed = True

        # Reconnect orphaned on-path nodes via out_adj
        op_children: set[int] = set()
        for s, t, l in edges_list:
            if s in on_path and t in on_path:
                op_children.add(t)

        roots_in_path = on_path - op_children
        if len(roots_in_path) > 1:
            original_roots: set[int] = set()
            for nid in roots_in_path:
                if not any(child == nid
                           for anc in on_path if anc != nid
                           for child, _ in out_adj.get(anc, [])):
                    original_roots.add(nid)
            orphans = roots_in_path - original_roots - matched_set
            if not original_roots:
                original_roots = {min(roots_in_path)}
                orphans = roots_in_path - original_roots - matched_set

            for orphan in orphans:
                for ancestor in sorted(on_path - orphans):
                    found = False
                    for child, label in out_adj.get(ancestor, []):
                        if child == orphan:
                            edges_list.append((ancestor, orphan, label))
                            found = True
                            break
                    if found:
                        break

    # --- step 3: filter navigational edges -----------------------------------
    if _pc:
        clean_edges = []
        for s, t, l in edges_list:
            if _is_navigational_edge(l, _pc):
                if s in on_path and t in on_path:
                    pass
                else:
                    continue
            clean_edges.append((s, t, l))
        edges_list = clean_edges

    # --- step 3b: backward clinical trace — prune false on-path nodes --------
    if _pc:
        rev_adj: dict[int, list[int]] = defaultdict(list)
        heuristic_pairs: set[tuple[int, int]] = set()
        for s, t, l in edges_list:
            if _is_heuristic_edge(l, _pc):
                heuristic_pairs.add((s, t))
            rev_adj[t].append(s)

        reachable: set[int] = set(matched_set)
        queue = list(matched_set & on_path)
        while queue:
            nid = queue.pop()
            for parent in rev_adj.get(nid, []):
                if parent in reachable:
                    continue
                if (parent, nid) in heuristic_pairs and nid not in matched_set:
                    continue
                reachable.add(parent)
                if parent in on_path:
                    queue.append(parent)

        false_on_path = on_path - reachable
        if false_on_path:
            on_path -= false_on_path
            edges_list = [
                (s, t, l) for s, t, l in edges_list
                if s not in false_on_path and t not in false_on_path
            ]

    # --- step 4: deduplicate edges -------------------------------------------
    seen: set[tuple[int, int]] = set()
    deduped: list[tuple[int, int, str]] = []
    for s, t, l in edges_list:
        key = (s, t)
        if key not in seen:
            seen.add(key)
            deduped.append((s, t, l))
    edges_list = deduped

    # --- step 5: add sibling branches (one level) ----------------------------
    sibling_nodes: set[int] = set()
    sibling_edges: set[tuple[int, int, str]] = set()

    for nid in list(on_path):
        for child_nid, edge_label in out_adj.get(nid, []):
            if child_nid in on_path or child_nid in matched_set:
                continue
            if _pc:
                child_title = node_by_id.get(child_nid, {}).get("title", "")
                if _is_navigational_node(child_title, _pc):
                    continue
                if _is_heuristic_edge(edge_label, _pc):
                    continue
            sibling_nodes.add(child_nid)
            sibling_edges.add((nid, child_nid, edge_label))

    all_visible = on_path | sibling_nodes | matched_set
    tree_nodes: dict[int, dict] = {}
    for nid in all_visible:
        node = node_by_id.get(nid, {})
        tree_nodes[nid] = {
            "id": nid,
            "title": node.get("title", ""),
            "content_preview": (node.get("content", "") or "")[:120],
            "page_id": node.get("page_id"),
            "on_path": nid in on_path,
            "is_matched": nid in matched_set,
            "is_sibling": nid in sibling_nodes,
        }

    all_edges = sorted(set(edges_list) | sibling_edges)
    all_edges = [(s, t, l) for s, t, l in all_edges if s in all_visible and t in all_visible]

    return {
        "nodes": tree_nodes,
        "edges": all_edges,
        "on_path_node_ids": sorted(on_path),
        "matched_node_ids": sorted(matched_set & set(node_by_id)),
        "sibling_node_ids": sorted(sibling_nodes),
    }


def _sanitize_label(text: str, page_codes: set[str] | None = None, max_len: int = 80) -> str:
    text = _strip_html(text)
    text = text.replace('"', "'").replace("\n", " ").strip()
    if page_codes:
        text = _clean_display_title(text, page_codes)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def _sanitize_edge_label(text: str, page_codes: set[str] | None = None, max_len: int = 120) -> str:
    text = _strip_html(text)
    text = text.replace('"', "'").replace("\n", " ").strip()
    if text.startswith("cross_page:"):
        return ""
    if page_codes:
        text = _clean_display_edge(text, page_codes)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def render_mermaid(tree: dict, page_codes: set[str] | None = None) -> str:
    nodes = tree.get("nodes", {})
    edges = tree.get("edges", [])
    if not nodes:
        return ""

    matched_set = set(tree.get("matched_node_ids", []))
    on_path_set = set(tree.get("on_path_node_ids", []))

    lines = ["graph TD"]

    for nid in sorted(nodes):
        info = nodes[nid]
        label = info["title"] or f"Node {nid}"
        label = _sanitize_label(label, page_codes=page_codes)
        if info["is_matched"]:
            cls = ":::matched"
        elif info["on_path"]:
            cls = ":::onpath"
        else:
            cls = ":::sibling"
        lines.append(f'  N{nid}["{label}"]{cls}')

    for src, tgt, label in edges:
        if src not in nodes or tgt not in nodes:
            continue
        edge_label = _sanitize_edge_label(label, page_codes=page_codes)
        if edge_label:
            lines.append(f'  N{src} -->|"{edge_label}"| N{tgt}')
        else:
            lines.append(f"  N{src} --> N{tgt}")

    lines.append("")
    lines.append("  classDef onpath fill:#4CAF50,color:white,stroke:#388E3C")
    lines.append("  classDef matched fill:#F44336,color:white,stroke:#D32F2F")
    lines.append("  classDef sibling fill:#E0E0E0,color:#616161,stroke:#BDBDBD")

    return "\n".join(lines)


def build_and_render(
    node_by_id: dict[int, dict],
    out_adj: dict[int, list[tuple[int, str]]],
    matched_node_ids: list[int],
    compact_paths: list[dict],
    page_codes: set[str] | None = None,
) -> dict:
    tree = build_pruned_tree(
        node_by_id, out_adj, matched_node_ids, compact_paths,
        page_codes=page_codes,
    )
    mermaid = render_mermaid(tree, page_codes=page_codes)
    return {
        "tree": tree,
        "mermaid": mermaid,
        "stats": {
            "on_path": len(tree["on_path_node_ids"]),
            "matched": len(tree["matched_node_ids"]),
            "siblings": len(tree["sibling_node_ids"]),
            "edges": len(tree["edges"]),
        },
    }
