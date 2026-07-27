from agent.explore.schema import WebSearchLink


class CitationFormatter:

    def vancouver(
        self,
        link: dict) -> str:
        res = ""
        if link.get('id') and link['id']:
            res += f"[{link['id']}]. "
        if link.get('author') and link['author'].strip():
            authors = link['author'].split(',')
            if len(authors) <= 6:
                res += f"{link['author']}. "
            else:
                authors = authors[:6]
                res += ",".join(authors) + " et al. "
        if link.get('title') and link['title'].strip():
            res += f"{link['title']}. "
        if link.get('full_journal_name') and link['full_journal_name'].strip():
            res += f"{link['full_journal_name']}. "
        if link.get('pub_date') and link['pub_date'].strip():
            res += f"{link['pub_date']}. "
        if link.get('doi') and link['doi'].strip():
            res += f"doi: {link['doi']}. "
        if link.get('url') and link['url'].strip():
            res += link['url']
        return res

