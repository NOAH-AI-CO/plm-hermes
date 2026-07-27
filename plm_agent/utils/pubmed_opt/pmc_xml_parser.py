# -*- coding: utf-8 -*-
import io

from lxml import etree
from typing import List, Optional, Dict

class PMCXMLParser:
    """
    PMC XML Parser Class
    Converts PMC (JATS/NLM) XML to plain text.
    Features:
    - Compatible with both namespaced and non-namespaced JATS XML
    - Extraction order: title, authors/affiliations, abstract, body sections, figures/tables, acknowledgments, references
    - Handles inline elements (xref, italic, bold, sup, sub, etc.) to plain text
    - Simplifies tables to plain text (tab-separated)
    - Efficient: uses only lxml; avoids unnecessary deep copies and string concatenation
    """

    @staticmethod
    def strip_ns(tag: Optional[str]) -> str:
        """Remove XML namespace from tag name"""
        if tag is None:
            return ""
        if not isinstance(tag, str):
            return ""
        return tag.split("}")[-1]

    @staticmethod
    def text_of(el) -> str:
        """
        Extract plain text from element and its descendants, preserving natural spacing.
        Handles common inline elements (italic/bold/sup/sub/xref) uniformly.
        """
        if el is None:
            return ""
        parts: List[str] = []

        def rec(node):
            # node.text
            if node.text:
                parts.append(node.text)

            # children
            for ch in node:
                if isinstance(ch.tag, str):
                    t = PMCXMLParser.strip_ns(ch.tag)
                    if t in {"italic", "bold", "underline", "em", "strong"}:
                        # Extract text directly; can wrap with markers if emphasis needed
                        rec(ch)
                    elif t in {"sup", "sub"}:
                        # Superscript/subscript merged into text
                        rec(ch)
                    elif t in {"xref"}:
                        # Cross-references: usually ref/fig/table numbers, extract visible text
                        rec(ch)
                    elif t in {"inline-formula", "tex-math"}:
                        # Inline formulas: use placeholder + extract possible visible text
                        inner = "".join(ch.itertext()).strip()
                        parts.append(f"[Formula:{inner}]" if inner else "[Formula]")
                    elif t in {"inline-graphic"}:
                        parts.append("[Inline-Graphic]")
                    else:
                        rec(ch)

                # node.tail
                if ch.tail:
                    parts.append(ch.tail)

        rec(el)
        # Normalize whitespace
        txt = " ".join(" ".join(parts).split())
        return txt

    @staticmethod
    def join_nonempty(lines: List[str], sep="\n") -> str:
        """Join non-empty lines with separator"""
        return sep.join([ln for ln in lines if ln and ln.strip()])
        
    @staticmethod
    def first(el, *paths):
        """Find first matching element from multiple XPath expressions"""
        for p in paths:
            found = el.xpath(p)
            if found:
                return found[0]
        return None

    @staticmethod
    def extract_title(root) -> str:
        """Extract article title from front matter"""
        title = root.xpath(
            "//*[local-name()='front']/*[local-name()='article-meta']/*[local-name()='title-group']/*[local-name()='article-title']")
        return PMCXMLParser.text_of(title[0]) if title else ""

    @staticmethod
    def extract_authors_aff(root) -> str:
        """Extract authors and their affiliations"""
        meta = root.xpath("//*[local-name()='front']/*[local-name()='article-meta']")
        if not meta:
            return ""
        meta = meta[0]
        contribs = meta.xpath(
            ".//*[local-name()='contrib-group']/*[local-name()='contrib'][@contrib-type='author' or not(@contrib-type)]")

        # Build affiliation map
        aff_map = {}
        for aff in meta.xpath(".//*[local-name()='aff']"):
            rid = aff.get("id") or aff.get("{http://www.w3.org/XML/1998/namespace}id")
            if rid:
                aff_map[rid] = PMCXMLParser.text_of(aff)

        authors = []
        for c in contribs:
            name_el = PMCXMLParser.first(c, ".//*[local-name()='name']")
            if name_el is not None:
                surname = PMCXMLParser.text_of(PMCXMLParser.first(name_el, "./*[local-name()='surname']")) or ""
                given = PMCXMLParser.text_of(PMCXMLParser.first(name_el, "./*[local-name()='given-names']")) or ""
                fullname = (given + " " + surname).strip() or PMCXMLParser.text_of(name_el)
            else:
                fullname = PMCXMLParser.text_of(c)

            # Extract affiliations via xref
            affs = []
            for xr in c.xpath(".//*[local-name()='xref' and (@ref-type='aff' or @ref-type='corresp')]"):
                rid = xr.get("rid")
                if rid and rid in aff_map:
                    affs.append(aff_map[rid])

            # Some XMLs have inline affiliations
            if not affs:
                inline_affs = c.xpath(".//*[local-name()='aff']")
                affs = [PMCXMLParser.text_of(a) for a in inline_affs if PMCXMLParser.text_of(a)]

            if affs:
                authors.append(f"{fullname} ({'; '.join(dict.fromkeys(affs))})")
            else:
                authors.append(fullname)

        if not authors:
            return ""
        return "Authors:\n" + "\n".join(authors)

    @staticmethod
    def extract_abstract(root) -> str:
        """Extract article abstract"""
        abs_nodes = root.xpath("//*[local-name()='front']/*[local-name()='article-meta']/*[local-name()='abstract']")
        chosen = [a for a in abs_nodes if (a.get("abstract-type") in (None, "", "summary"))]
        if not chosen and abs_nodes:
            chosen = abs_nodes
        parts = []
        for a in chosen:
            # Some abstracts have sections or paragraphs
            secs = a.xpath("./*[local-name()='sec']")
            if secs:
                for s in secs:
                    label = PMCXMLParser.text_of(PMCXMLParser.first(s, "./*[local-name()='title']")) or ""
                    paras = [PMCXMLParser.text_of(p) for p in s.xpath(".//*[local-name()='p']")]
                    body = PMCXMLParser.join_nonempty(paras, "\n")
                    parts.append(PMCXMLParser.join_nonempty([label, body], "\n") if body else label)
            else:
                paras = [PMCXMLParser.text_of(p) for p in a.xpath(".//*[local-name()='p']")]
                if not paras:
                    paras = [" ".join(a.itertext()).strip()]
                parts.append(PMCXMLParser.join_nonempty(paras, "\n"))

        txt = PMCXMLParser.join_nonempty(parts, "\n\n")
        return f"Abstract:\n{txt}" if txt else ""

    @staticmethod
    def extract_sections(root) -> str:
        """Extract main body sections with multi-level hierarchy"""
        bodies = root.xpath("//*[local-name()='body']")
        if not bodies:
            return ""
        body = bodies[0]

        out_lines: List[str] = []

        def handle_list(list_el):
            """Process list elements"""
            items = []
            for li in list_el.xpath("./*[local-name()='list-item']"):
                ps = li.xpath(".//*[local-name()='p']")
                if ps:
                    for p in ps:
                        items.append(f"- {PMCXMLParser.text_of(p)}")
                else:
                    items.append(f"- {PMCXMLParser.text_of(li)}")
            return "\n".join(items)

        def handle_table(table_wrap):
            """Process table elements"""
            is_table = PMCXMLParser.strip_ns(getattr(table_wrap, "tag", None)) == "table"
            if is_table:
                cap_text = ""
                table = table_wrap
            else:
                cap = PMCXMLParser.first(table_wrap, "./*[local-name()='caption']")
                cap_text = PMCXMLParser.text_of(cap) if cap is not None else ""
                table = PMCXMLParser.first(table_wrap, ".//*[local-name()='table']")
            rows_out = []
            if table is not None:
                rows = table.xpath(".//*[local-name()='tr']")
                for r in rows:
                    cells = r.xpath("./*[local-name()='td']|./*[local-name()='th']")
                    cell_txt = [PMCXMLParser.text_of(c) for c in cells]
                    rows_out.append("\t".join(cell_txt))
            tblock = PMCXMLParser.join_nonempty(rows_out, "\n")
            if tblock:
                return PMCXMLParser.join_nonempty([f"[Table] {cap_text}", tblock], "\n")
            else:
                return f"[Table] {cap_text}" if cap_text else "[Table]"

        def handle_fig(fig_wrap):
            """Process figure elements"""
            label = PMCXMLParser.text_of(PMCXMLParser.first(fig_wrap, "./*[local-name()='label']"))
            cap = PMCXMLParser.text_of(PMCXMLParser.first(fig_wrap, "./*[local-name()='caption']"))
            if label and cap:
                return f"[Figure {label}] {cap}"
            elif cap:
                return f"[Figure] {cap}"
            elif label:
                return f"[Figure {label}]"
            return "[Figure]"

        def walk_sec(sec, level=1):
            """Recursively walk through section hierarchy"""
            title = PMCXMLParser.text_of(PMCXMLParser.first(sec, "./*[local-name()='title']"))
            title_line = ("#" * min(level, 6)) + " " + title if title else ""
            if title_line:
                out_lines.append(title_line)

            # Content order: p / list / fig / table / sub-sec
            for node in sec:
                t = PMCXMLParser.strip_ns(getattr(node, "tag", None))
                if t == "p":
                    out_lines.append(PMCXMLParser.text_of(node))
                elif t == "list":
                    out_lines.append(handle_list(node))
                elif t == "fig":
                    out_lines.append(handle_fig(node))
                elif t in {"table-wrap", "table"}:
                    out_lines.append(handle_table(node))
                elif t == "sec":
                    walk_sec(node, level + 1)
                elif t in {"disp-quote", "boxed-text", "disp-formula"}:
                    out_lines.append(PMCXMLParser.text_of(node))

        # Recursively walk from body at level 0 to keep perfect document order
        # and capture paragraphs/elements directly under body.
        walk_sec(body, level=0)

        return PMCXMLParser.join_nonempty(out_lines, "\n\n")

    @staticmethod
    def extract_ack(root) -> str:
        """Extract acknowledgments section"""
        acks = root.xpath("//*[local-name()='ack']")
        parts = []
        for a in acks:
            title = PMCXMLParser.text_of(PMCXMLParser.first(a, "./*[local-name()='title']"))
            paras = [PMCXMLParser.text_of(p) for p in a.xpath(".//*[local-name()='p']")]
            blk = PMCXMLParser.join_nonempty(paras, "\n")
            parts.append(PMCXMLParser.join_nonempty([title, blk], "\n") if blk or title else "")
        txt = PMCXMLParser.join_nonempty(parts, "\n\n")
        return f"Acknowledgments:\n{txt}" if txt else ""

    @staticmethod
    def extract_refs(root) -> str:
        """Extract references section"""
        ref_lists = root.xpath("//*[local-name()='ref-list']")
        if not ref_lists:
            return ""
        out = []
        idx = 1
        for rl in ref_lists:
            for ref in rl.xpath("./*[local-name()='ref']"):
                # References may be in <element-citation> / <mixed-citation> / <nlm-citation>
                cit = PMCXMLParser.first(ref, "./*[local-name()='element-citation']",
                                         "./*[local-name()='mixed-citation']",
                                         "./*[local-name()='nlm-citation']")
                if cit is not None:
                    txt = PMCXMLParser.text_of(cit).strip()
                else:
                    txt = PMCXMLParser.text_of(ref).strip()
                if txt:
                    out.append(f"[{idx}] {txt}")
                    idx += 1
        return "References:\n" + "\n".join(out) if out else ""

    @classmethod
    def parse(cls, xml_string: str) -> dict:
        """
        Parse PMC XML string and return plain text

        Args:
            xml_string: XML content as string

        Returns:
            Plain text with all sections combined
        """
        parser = etree.XMLParser(
            recover=True,
            remove_blank_text=True,
            resolve_entities=False,
            huge_tree=True,
            remove_comments=True
        )

        try:
            # Parse XML string
            tree = etree.parse(io.BytesIO(xml_string.encode('utf-8')), parser)
            root = tree.getroot()

            # Extract all sections
            title = cls.extract_title(root)
            authors_aff = cls.extract_authors_aff(root)
            abstract = cls.extract_abstract(root)
            body = cls.extract_sections(root)
            ack = cls.extract_ack(root)
            refs = cls.extract_refs(root)

            # Combine non-empty sections
            parts = {}
            if title: parts['title'] = title.strip()
            if authors_aff: parts['authors_aff'] = authors_aff.strip()
            if abstract: parts['abstract'] = abstract.strip()
            if body: parts['body'] = body.strip()
            if ack: parts['ack'] = ack.strip()
            if refs: parts['refs'] = refs.strip()

            return parts

        except Exception as e:
            raise ValueError(f"Failed to parse XML: {str(e)}")