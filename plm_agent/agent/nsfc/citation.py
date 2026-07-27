import re, json
from typing import List, Dict, Any, Tuple

CITE_CHUNK_RE = re.compile(r'\[(.*?)\]')
RANGE_RE = re.compile(r'^\d+\s*[-–]\s*\d+$')
INT_RE = re.compile(r'^\d+$')

def _expand_chunk_to_ids(chunk: str) -> List[int]:
    ids = []
    parts = [p.strip() for p in chunk.split(',') if p.strip()]
    for p in parts:
        if INT_RE.match(p):
            ids.append(int(p))
        elif RANGE_RE.match(p):
            a, b = re.split(r'[-–]', p)
            a, b = int(a.strip()), int(b.strip())
            lo, hi = (a, b) if a <= b else (b, a)
            ids.extend(list(range(lo, hi+1)))
    return ids

def parse_citation_numbers(text: str) -> List[int]:
    used = []
    for inner in CITE_CHUNK_RE.findall(text):
        for cid in _expand_chunk_to_ids(inner):
            used.append(cid)
    return used

def find_first_appearance_order(text: str, N: int) -> List[int]:
    first_seen_pos = {}
    pos = 0
    for m in CITE_CHUNK_RE.finditer(text):
        for cid in _expand_chunk_to_ids(m.group(1)):
            if 1 <= cid <= N and cid not in first_seen_pos:
                first_seen_pos[cid] = pos
        pos += 1

    appeared = sorted(first_seen_pos.keys(), key=lambda k: first_seen_pos[k])
    not_seen = [i for i in range(1, N+1) if i not in first_seen_pos]
    return appeared + not_seen


def _compress_ids_to_ranges(nums: List[int]) -> str:
    if not nums:
        return ""
    nums = sorted(set(nums))
    ranges = []
    start = prev = nums[0]
    for x in nums[1:]:
        if x == prev + 1:
            prev = x
        else:
            ranges.append(f"{start}" if start == prev else f"{start}–{prev}")
            start = prev = x
    ranges.append(f"{start}" if start == prev else f"{start}–{prev}")
    return ",".join(ranges)

def renumber_text_by_order(text: str, order_old_ids: List[int]) -> Tuple[str, Dict[int, int]]:
    id_map = {old: (i+1) for i, old in enumerate(order_old_ids)}  # old -> new

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        old_ids = _expand_chunk_to_ids(inner)
        new_ids = [id_map.get(x, x) for x in old_ids]
        return "[" + _compress_ids_to_ranges(new_ids) + "]"

    new_text = CITE_CHUNK_RE.sub(repl, text)
    return new_text, id_map

def reorder_full_records_by_order(records: List[Dict[str, Any]], order_old_ids: List[int]) -> List[Dict[str, Any]]:

    id_map = {old: (i+1) for i, old in enumerate(order_old_ids)}  # old -> new

    tmp = []
    for old_id, rec in enumerate(records, start=1):
        new_id = id_map.get(old_id, old_id)
        tmp.append((new_id, rec))

    tmp.sort(key=lambda x: x[0])

    return [rec for _, rec in tmp]


def _parse_citation_block(block: str) -> list[int]:
    """
    把方括号内部的内容解析成一串数字：
    - '1,2,4-6' -> [1,2,4,5,6]
    - 支持中文/英文逗号，支持 1-3 范围
    """
    nums: list[int] = []
    parts = re.split(r'[，,]\s*', block)
    for p in parts:
        p = p.strip()
        if not p:
            continue
        m = re.match(r'^(\d+)\s*[-–]\s*(\d+)$', p)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b:
                nums.extend(range(a, b + 1))
            else:
                nums.extend(range(b, a + 1))
        else:
            if p.isdigit():
                nums.append(int(p))
    # 去重保序
    seen = set()
    out = []
    for x in nums:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extract_citation_order(*texts: str) -> list[int]:
    """从多段文本中按出现顺序抽取全局引用编号"""
    order: list[int] = []
    for text in texts:
        if not text:
            continue
        for m in re.finditer(r'\[([^\]]+)\]', text):
            block = m.group(1)
            nums = _parse_citation_block(block)
            for n in nums:
                if n not in order:
                    order.append(n)
    return order


def _renumber_text_with_map(text: str, id_map: dict[int, int]) -> str:
    """根据 old->new 映射重写一段正文里的 [..] 引用"""
    if not text:
        return text

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        olds = _parse_citation_block(inner)
        if not olds:
            return m.group(0)
        # 映射并去重排序
        news = sorted({id_map.get(o, o) for o in olds})
        if not news:
            return m.group(0)

        ranges: list[str] = []
        start = news[0]
        prev = news[0]
        for x in news[1:]:
            if x == prev + 1:
                prev = x
            else:
                ranges.append(str(start) if start == prev else f"{start}-{prev}")
                start = x
                prev = x
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        return "[" + ",".join(ranges) + "]"

    return re.sub(r'\[([^\]]+)\]', repl, text)


def _split_literature_blocks(snips: str) -> list[dict]:
    """
    把 literature_snippets 拆成：
    [
      {"index": 1, "text": "[1] xxx\n    摘要要点：..."},
      ...
    ]
    """
    if not snips:
        return []
    lines = snips.splitlines()
    entries: list[dict] = []
    cur_idx = None
    cur_lines: list[str] = []
    for line in lines:
        m = re.match(r'^\s*\[(\d+)\]', line)
        if m:
            if cur_idx is not None:
                entries.append({"index": cur_idx, "text": "\n".join(cur_lines).rstrip()})
            cur_idx = int(m.group(1))
            cur_lines = [line]
        else:
            if cur_idx is not None:
                cur_lines.append(line)
    if cur_idx is not None:
        entries.append({"index": cur_idx, "text": "\n".join(cur_lines).rstrip()})
    return entries


def _reorder_literature(snips: str, citation_order: list[int]) -> str:
    """按全局 citation_order 重排参考文献列表"""
    if not snips or not citation_order:
        return snips

    entries = _split_literature_blocks(snips)
    if not entries:
        return snips

    by_old = {e["index"]: e for e in entries}
    ordered_items = []
    for old_idx in citation_order:
        if old_idx in by_old:
            ordered_items.append(by_old[old_idx])

    out_lines: list[str] = []
    for new_idx, entry in enumerate(ordered_items, 1):
        old_idx = entry["index"]
        txt = entry["text"]
        # 改行首 [old] -> [new]
        new_txt = re.sub(r'^\s*\[' + str(old_idx) + r'\]', f"[{new_idx}]", txt, count=1)
        out_lines.append(new_txt)
        out_lines.append("")

    return "\n".join(out_lines).rstrip()


if __name__ == "__main__":
    from agent.nsfc.nsfc_query_database import vector_search_pubmed
    
    records = vector_search_pubmed(user_input="cancer immunotherapy", top_k=10)
    draft = """开篇……参考综述见 [8,9]。免疫组合策略进展 [5–6] …… 肿瘤新抗原方向 [6] …… 围手术期 IO 证据 [1] ……"""

    N = len(records)

    # a) 找“首次出现顺序”
    order_old_ids = find_first_appearance_order(draft, N)  # e.g. [8,9,5,6,1,2,3,4,...]
    print("Order of first appearance:", order_old_ids)

    # b) 重写正文引用到新编号（可选，但通常需要）
    draft_after, id_map = renumber_text_by_order(draft, order_old_ids)
    print("Id map (old->new):", id_map)

    # c) 按同样顺序重排原始参考列表（保持同样的数据格式）
    records_after = reorder_full_records_by_order(records, order_old_ids)

    # d) 如需保存 JSON（确保 Unicode/中文不转义）
    with open("references_reordered.json", "w", encoding="utf-8") as f:
        json.dump(records_after, f, ensure_ascii=False, indent=2)

    # e) 也可以保存重写后的正文
    with open("draft_after_renumber.md", "w", encoding="utf-8") as f:
        f.write(draft_after)

    # 额外：导出 old->new 对照表，方便回查
    crosswalk = [{"old_id": old, "new_id": new} for old, new in sorted(id_map.items(), key=lambda x: x[1])]
    with open("id_crosswalk.json", "w", encoding="utf-8") as f:
        json.dump(crosswalk, f, ensure_ascii=False, indent=2)

    print("Done.")