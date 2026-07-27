# -*- coding: utf-8 -*-
from markdown_it import MarkdownIt

def parse_blocks(md_text: str):
    """
    Parse Markdown into structured blocks
    
    Returns:
        list[dict]: List of blocks with {'id', 'type', ...}
    """
    md = MarkdownIt('commonmark', {'html': False}).enable('table')
    toks = md.parse(md_text)
    blocks, i, n = [], 0, len(toks)
    block_id = 0
    table_id = 0

    while i < n:
        t = toks[i]

        # ---------- Heading ----------
        if t.type == 'heading_open':
            # Boundary check
            if i + 2 >= n:
                i += 1
                continue
            
            level = int(t.tag[1])  # 'h2' -> 2
            text = toks[i + 1].content
            blocks.append({
                'id': block_id,
                'type': 'heading',
                'level': level,
                'text': text
            })
            block_id += 1
            i += 3  # Skip heading_open/inline/heading_close

        # ---------- Paragraph ----------
        elif t.type == 'paragraph_open':
            if i + 2 >= n:
                i += 1
                continue
            
            text = toks[i + 1].content
            blocks.append({
                'id': block_id,
                'type': 'paragraph',
                'text': text
            })
            block_id += 1
            i += 3  # Skip paragraph_open/inline/paragraph_close

        # ---------- Table ----------
        elif t.type == 'table_open':
            rows = []
            i += 1
            
            while i < n and toks[i].type != 'table_close':
                # Skip thead/tbody structure markers
                if toks[i].type in ('thead_open', 'tbody_open', 'thead_close', 'tbody_close'):
                    i += 1
                    continue
                
                # Parse table row
                if toks[i].type == 'tr_open':
                    row = []
                    i += 1
                    
                    while i < n and toks[i].type != 'tr_close':
                        # Skip th/td tags, extract inline content
                        if toks[i].type in ('th_open', 'td_open'):
                            i += 1
                            if i < n and toks[i].type == 'inline':
                                row.append(toks[i].content.strip())
                                i += 1
                            if i < n and toks[i].type in ('th_close', 'td_close'):
                                i += 1
                        else:
                            i += 1
                    
                    if row:  # Only add non-empty rows
                        rows.append(row)
                    i += 1  # Skip tr_close
                else:
                    i += 1
            
            # Create single table block with all rows
            if rows:
                for row in rows:
                    blocks.append({
                        'id': block_id,
                        'table_id': table_id,
                        'type': 'table_row',
                        'rows': row,
                        'header': rows[0] if rows else []
                    })
                    block_id += 1
                table_id += 1
            
            i += 1  # Skip table_close

        else:
            i += 1  # Skip other tokens

    return blocks

def merge_blocks(blocks: list[dict]) -> str:
    """
    Merge structured blocks back into Markdown text
    
    Args:
        blocks: List of blocks from parse_blocks with {'id', 'type', ...}
    
    Returns:
        str: Reconstructed Markdown text
    """
    if not blocks:
        return ""
    
    md_lines = []
    processed_tables = set()
    
    for block in blocks:
        block_type = block.get('type')
        
        # ---------- Heading ----------
        if block_type == 'heading':
            level = block.get('level', 1)
            text = block.get('text', '')
            md_lines.append('#' * level + ' ' + text)
            md_lines.append('')  # Add blank line after heading
        
        # ---------- Paragraph ----------
        elif block_type == 'paragraph':
            text = block.get('text', '')
            md_lines.append(text)
            md_lines.append('')  # Add blank line after paragraph
        
        # ---------- Table ----------
        elif block_type == 'table_row':
            table_id = block.get('table_id')
            
            # Skip if this table has already been processed
            if table_id in processed_tables:
                continue
            
            processed_tables.add(table_id)
            
            # Collect all rows for this table
            table_rows = [b['rows'] for b in blocks 
                         if b.get('type') == 'table_row' 
                         and b.get('table_id') == table_id]
            
            if not table_rows:
                continue
            
            # Calculate column widths for alignment
            num_cols = len(table_rows[0]) if table_rows else 0
            col_widths = [0] * num_cols
            
            for row in table_rows:
                for i, cell in enumerate(row):
                    if i < num_cols:
                        col_widths[i] = max(col_widths[i], len(cell))
            
            # Write table rows
            for idx, row in enumerate(table_rows):
                # Pad cells to column width
                padded_cells = [cell.ljust(col_widths[i]) 
                               for i, cell in enumerate(row)]
                md_lines.append('| ' + ' | '.join(padded_cells) + ' |')
                
                # Add separator after header (first row)
                if idx == 0:
                    separators = ['-' * col_widths[i] for i in range(num_cols)]
                    md_lines.append('| ' + ' | '.join(separators) + ' |')
            
            md_lines.append('')  # Add blank line after table
    
    # Join lines and clean up extra blank lines at the end
    result = '\n'.join(md_lines).rstrip('\n')
    return result


def test_markdown_parser():
    content: str = r"""# Latest Advances in Migraine Pathogenesis (2023–2025)

---

## Overview

Recent research continues to refine a multi‐system view of migraine involving the trigeminovascular network, cortical spreading depolarization (CSD) and aura, neuroinflammation with innate immune signaling, neuron–glia interactions, and dysregulated ion channel/receptor function. These advances link early cortical events to peripheral trigeminal activation and identify several therapeutic targets beyond CGRP, including PACAP/PAC1, purinergic P2X3, TRP channels (TRPM8), chemokine signaling (CCL2–CCR2), and potassium channel pathways[1](https://pubmed.ncbi.nlm.nih.gov/36907522)[2](https://pubmed.ncbi.nlm.nih.gov/36795624)[3](https://pubmed.ncbi.nlm.nih.gov/37370051).

---

## Key Mechanistic Themes and 2023–2025 Highlights

- Trigeminovascular activation and CGRP
  - CGRP remains central in migraine; CSD increases CGRP mRNA in trigeminal ganglion neurons, offering a mechanistic bridge between aura and trigeminovascular peptide upregulation[4](https://pubmed.ncbi.nlm.nih.gov/37511336). Anti‐CGRP medications modulate behaviors in rodent dural inflammation models, supporting relevance to neuroinflammation‐linked pain pathways[5](https://pubmed.ncbi.nlm.nih.gov/36908624).

- CSD–innate immunity linkage via neuronal NLRP3
  - Neuronal NLRP3 inflammasome mediates CSD‐evoked trigeminovascular activation, implicating innate immune signaling within neurons as a critical link from aura to headache pain[2](https://pubmed.ncbi.nlm.nih.gov/36795624)[6](https://pubmed.ncbi.nlm.nih.gov/36795624/)[7](https://painresearchforum.org/paper/neuronal-nlrp3-inflammasome-mediates-spreading-depolarization-evoked-trigeminovascular-activation).

- Emerging innate immune pathway: cGAS–STING
  - Preclinical work suggests CSD may activate the cGAS–STING pathway, further connecting cortical depolarization to innate immune responses; this is an emerging area and includes preprint data requiring confirmation[8](https://www.researchsquare.com/article/rs-7160141/latest).

- Neuroinflammation and neuroimmune interactions
  - Updated reviews emphasize roles of immune cells, inflammatory mediators, and neurogenic inflammation in initiating and sustaining migraine pain, including peripheral and central sensitization processes[1](https://pubmed.ncbi.nlm.nih.gov/36907522)[9](https://pubmed.ncbi.nlm.nih.gov/36907522/)[10](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236%2824%2900152-8).

- Glial cells and neuron–glia crosstalk
  - Microglia and astrocytes contribute across phases of migraine; their crosstalk is increasingly viewed as a targetable driver of neuroinflammation and chronification[11](https://pubmed.ncbi.nlm.nih.gov/37628733)[12](https://www.aginganddisease.org/EN/10.14336/AD.2023.0623)[13](https://www.ibroneuroscience.org/article/S0306-4522%2824%2900509-8/fulltext).

- Ion channels and receptor signaling
  - TRPM8 activation increases susceptibility to CSD and facilitates trigeminal neuroinflammation, linking sensory channel activity to cortical and peripheral migraine pathways[14](https://pubmed.ncbi.nlm.nih.gov/40087597).
  - Potassium channel signaling is implicated in pathophysiology, with interest in modulators of neuronal excitability and vascular tone as potential therapeutic strategies[15](https://pubmed.ncbi.nlm.nih.gov/36986537).
  - ATP acting on P2X3 receptors on trigeminal afferents contributes to nociceptive signaling in migraine, highlighting purinergic targets[16](https://pubmed.ncbi.nlm.nih.gov/36597043).

- Chemokines and peripheral sensitization
  - Peripheral CCL2–CCR2 signaling plays a role in chronic headache‐related sensitization, suggesting a mechanism for conversion to chronic migraine and a potential target to interrupt peripheral input[17](https://pubmed.ncbi.nlm.nih.gov/37284790).

---

## Mechanisms, Evidence, and Therapeutic Implications

| Mechanism | Key recent findings (2023–2025) | Evidence type | Therapeutic implications |
|---|---|---|---|
| CSD → trigeminovascular via neuronal NLRP3 | CSD activates neuronal NLRP3 inflammasome, driving trigeminovascular activation and linking aura to headache[2](https://pubmed.ncbi.nlm.nih.gov/36795624)[6](https://pubmed.ncbi.nlm.nih.gov/36795624/)[7](https://painresearchforum.org/paper/neuronal-nlrp3-inflammasome-mediates-spreading-depolarization-evoked-trigeminovascular-activation) | Preclinical (rodent, mechanistic) | Innate immunity inhibitors (e.g., NLRP3 or upstream Panx1 pore modulators) may interrupt aura–pain coupling[2](https://pubmed.ncbi.nlm.nih.gov/36795624)[7](https://painresearchforum.org/paper/neuronal-nlrp3-inflammasome-mediates-spreading-depolarization-evoked-trigeminovascular-activation) |
| CSD → increased CGRP transcription | CSD upregulates CGRP mRNA in trigeminal ganglion neurons, connecting cortical events to peripheral peptide release[4](https://pubmed.ncbi.nlm.nih.gov/37511336) | Preclinical | Reinforces rationale for anti‐CGRP therapies and suggests timing considerations around aura[4](https://pubmed.ncbi.nlm.nih.gov/37511336) |
| Neuroinflammation and neuroimmune interactions | Reviews synthesize roles of immune cells, cytokines, and neurogenic inflammation in initiating/sustaining migraine[1](https://pubmed.ncbi.nlm.nih.gov/36907522)[9](https://pubmed.ncbi.nlm.nih.gov/36907522/)[10](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236%2824%2900152-8) | Reviews (human/animal) | Anti‐inflammatory strategies, microglia/astrocyte modulators, and neuroimmune pathway inhibitors[1](https://pubmed.ncbi.nlm.nih.gov/36907522)[10](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236%2824%2900152-8) |
| Glia (microglia/astrocytes) | Glia active in multiple migraine phases; crosstalk drives neuroinflammation and chronification[11](https://pubmed.ncbi.nlm.nih.gov/37628733)[12](https://www.aginganddisease.org/EN/10.14336/AD.2023.0623)[13](https://www.ibroneuroscience.org/article/S0306-4522%2824%2900509-8/fulltext) | Reviews; preclinical | Target glial signaling to reduce central sensitization and chronification[12](https://www.aginganddisease.org/EN/10.14336/AD.2023.0623)[13](https://www.ibroneuroscience.org/article/S0306-4522%2824%2900509-8/fulltext) |
| TRPM8 (TRP channel) | TRPM8 activation raises CSD susceptibility and trigeminal neuroinflammation[14](https://pubmed.ncbi.nlm.nih.gov/40087597) | Preclinical | TRPM8 modulation to lower cortical excitability/neuroinflammation[14](https://pubmed.ncbi.nlm.nih.gov/40087597) |
| Potassium channels | K+ channel signaling implicated in migraine pathophysiology; modulators under consideration[15](https://pubmed.ncbi.nlm.nih.gov/36986537) | Review | Ion channel modulators to stabilize neuronal excitability/vascular function[15](https://pubmed.ncbi.nlm.nih.gov/36986537) |
| Purinergic (ATP–P2X3) | ATP signaling via P2X3 on trigeminal neurons contributes to migraine nociception[16](https://pubmed.ncbi.nlm.nih.gov/36597043) | Review | P2X3 antagonists as analgesic candidates in migraine[16](https://pubmed.ncbi.nlm.nih.gov/36597043) |
| Chemokines (CCL2–CCR2) | Peripheral CCL2–CCR2 drives chronic headache sensitization[17](https://pubmed.ncbi.nlm.nih.gov/37284790) | Preclinical | CCR2/CCL2 pathway inhibition to prevent/ameliorate chronification[17](https://pubmed.ncbi.nlm.nih.gov/37284790) |
| PACAP–PAC1 | PAC1 inhibition effective in opioid-induced hyperalgesia and MOH models, supporting PACAP pathway relevance to migraine[18](https://pubmed.ncbi.nlm.nih.gov/36756376) | Preclinical | PACAP/PAC1 antagonists as candidates, especially in MOH contexts[18](https://pubmed.ncbi.nlm.nih.gov/36756376) |
| cGAS–STING (innate immunity) | CSD may activate cGAS–STING; preliminary status pending peer review[8](https://www.researchsquare.com/article/rs-7160141/latest) | Preprint | Potential innate immune target pending validation[8](https://www.researchsquare.com/article/rs-7160141/latest) |

---

## Peripheral vs Central Initiation: Ongoing Debate

- There is active debate on whether migraine attacks originate peripherally (meningeal/trigeminal) or centrally (cortex/brainstem). Recent discussions emphasize that both peripheral inputs and central mechanisms contribute, and their relative primacy may differ across patients or attack phenotypes[19](https://pubmed.ncbi.nlm.nih.gov/36627561). The NLRP3 findings following CSD support a central initiation route for aura‐linked attacks that secondarily engages trigeminovascular pathways[2](https://pubmed.ncbi.nlm.nih.gov/36795624)[7](https://painresearchforum.org/paper/neuronal-nlrp3-inflammasome-mediates-spreading-depolarization-evoked-trigeminovascular-activation).

---

## Genetics and Ion Channel Dysregulation

- Hemiplegic Migraine provides genetic support for ion channel/transport regulation as a pathogenic axis, reinforcing the role of neuronal excitability changes in migraine biology[20](https://pubmed.ncbi.nlm.nih.gov/37247170). Broader editorial and review work also situates ion channels as key contributors across neuropathologies, including migraine[21](https://pubmed.ncbi.nlm.nih.gov/36994098)[15](https://pubmed.ncbi.nlm.nih.gov/36986537).

---

## Future Therapeutic Targets Beyond CGRP

- Comprehensive reviews summarize non‐CGRP targets with mechanistic rationale (e.g., PACAP/PAC1, TRP channels including TRPM8, purinergic P2X3, K+ channels, chemokines, and brain reward circuits). While clinical efficacy for many is not yet established, human provocation and preclinical data continue to refine prioritization and trial design[3](https://pubmed.ncbi.nlm.nih.gov/37370051)[22](https://pubmed.ncbi.nlm.nih.gov/37370051/)[23](https://www.thelancet.com/journals/laneur/article/PIIS1474-4422%2824%2900003-6/abstract).
- The search for alternatives is driven by nonresponse rates to CGRP‐targeted treatments, underlining unmet need in prevention and acute care[24](https://www.iasp-pain.org/publications/pain-research-forum/papers-of-the-week/paper/future-targets-for-migraine-treatment-beyond-cgrp/).

---

## Imaging and Structural Correlates

- The association between migraine and white matter hyperintensities is being reconsidered, with recent work questioning the strength or implications of this link; mechanistic significance remains uncertain[25](https://pubmed.ncbi.nlm.nih.gov/40237025).

---

## What’s Emerging vs Established

- Established
  - Trigeminovascular activation and CGRP biology, with translational links from CSD to peripheral neuropeptide signaling[4](https://pubmed.ncbi.nlm.nih.gov/37511336)[5](https://pubmed.ncbi.nlm.nih.gov/36908624).
  - Neuroinflammation, neuron–glia crosstalk, and peripheral/central sensitization as core contributors to attack generation and chronification[1](https://pubmed.ncbi.nlm.nih.gov/36907522)[11](https://pubmed.ncbi.nlm.nih.gov/37628733)[10](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236%2824%2900152-8).

- Emerging
  - Neuronal NLRP3 inflammasome as the mechanistic bridge from aura (CSD) to trigeminovascular activation[2](https://pubmed.ncbi.nlm.nih.gov/36795624)[7](https://painresearchforum.org/paper/neuronal-nlrp3-inflammasome-mediates-spreading-depolarization-evoked-trigeminovascular-activation).
  - cGAS–STING activation by CSD (preprint), requiring replication and peer‐reviewed confirmation[8](https://www.researchsquare.com/article/rs-7160141/latest).
  - Specific ion channel/receptor targets (TRPM8, K+ channels, P2X3) as druggable nodes supported by preclinical data and mechanistic reviews[14](https://pubmed.ncbi.nlm.nih.gov/40087597)[15](https://pubmed.ncbi.nlm.nih.gov/36986537)[16](https://pubmed.ncbi.nlm.nih.gov/36597043).

---

## Practical Implications for Research and Development

- Integrate mechanistic timing: Aura‐linked CSD may prime CGRP and innate immunity; consider time-sensitive interventions around aura onset in trials[4](https://pubmed.ncbi.nlm.nih.gov/37511336)[2](https://pubmed.ncbi.nlm.nih.gov/36795624).
- Combine central and peripheral targets: Dual strategies that modulate cortical excitability/innate immunity and dampen trigeminal afferent input may improve efficacy and reduce chronification risk[1](https://pubmed.ncbi.nlm.nih.gov/36907522)[17](https://pubmed.ncbi.nlm.nih.gov/37284790).
- Prioritize glia and neuroimmune modulators: Microglia/astrocyte pathways are promising for preventing central sensitization in chronic migraine[12](https://www.aginganddisease.org/EN/10.14336/AD.2023.0623)[13](https://www.ibroneuroscience.org/article/S0306-4522%2824%2900509-8/fulltext)[11](https://pubmed.ncbi.nlm.nih.gov/37628733).
- Broaden target landscape beyond CGRP: Advance PACAP/PAC1, P2X3, TRPM8, K+ channel modulators, and chemokine inhibitors into rigorous clinical testing, guided by human provocation and biomarker frameworks[3](https://pubmed.ncbi.nlm.nih.gov/37370051)[22](https://pubmed.ncbi.nlm.nih.gov/37370051/)[23](https://www.thelancet.com/journals/laneur/article/PIIS1474-4422%2824%2900003-6/abstract).

---

## Notes on Evidence Quality

- Some highlighted findings derive from preclinical models; translation to humans requires clinical trials. The cGAS–STING report is a preprint and should be interpreted cautiously until peer review is complete[8](https://www.researchsquare.com/article/rs-7160141/latest).
- The literature debates origin and mechanistic weighting; heterogeneity across migraine subtypes (e.g., with vs without aura) likely influences the relative contribution of each pathway[19](https://pubmed.ncbi.nlm.nih.gov/36627561)[2](https://pubmed.ncbi.nlm.nih.gov/36795624).

---

If you would like, I can extract specific figures or mechanistic diagrams from any of the cited open‐access articles and build a focused briefing on one pathway (e.g., neuronal NLRP3 after CSD) or a comparative target assessment beyond CGRP."""

    blocks = parse_blocks(content)
    print(blocks)

    text = merge_blocks(blocks)
    print(text)

if __name__ == "__main__":
    test_markdown_parser()
