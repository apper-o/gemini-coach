import re
import html


RE_HR = re.compile(r'^(?:-{3,}|={3,})$')
RE_TABLE_DIVIDER = re.compile(r'^:?-+:?$')
RE_HEADING = re.compile(r'^(#{1,4})\s+(.*)$')
RE_BOLD = re.compile(r'\*\*(.*?)\*\*')
RE_ITALIC_STAR = re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)')
RE_ITALIC_UNDERSCORE = re.compile(r'(?<!_)_([^_]+)_(?!_)')
RE_MARKDOWN_STRIP = re.compile(r'[*_`]')


def _format_inline_markdown(text):
    """Konwertuje pogrubienie oraz kursywę Markdown na tagi HTML."""
    text = RE_BOLD.sub(r'<strong>\1</strong>', text)
    text = RE_ITALIC_STAR.sub(r'<em>\1</em>', text)
    return RE_ITALIC_UNDERSCORE.sub(r'<em>\1</em>', text)


def markdown_to_html_doc(md_text, title="Raport Coach Gemini"):
    """
    Konwertuje raport w formacie Markdown na pełny, nowoczesny dokument HTML.

    Dokument jest zoptymalizowany pod kątem ekranów smartfonów, włączając tryb ciemny
    (Dark Mode) oraz responsywne tabele. Obsługuje podstawowe znaczniki Markdown takie
    jak nagłówki, pogrubienia, listy i tabele.

    Args:
        md_text (str): Treść raportu w formacie Markdown.
        title (str, optional): Tytuł dokumentu HTML. Domyślnie "Raport Coach Gemini".

    Returns:
        str: Pełny kod HTML wygenerowanego dokumentu.
    """
    html_lines = []
    in_table = False
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def close_table():
        nonlocal in_table
        if in_table:
            html_lines.append("</tbody></table></div>")
            in_table = False

    for line in md_text.splitlines():
        stripped = line.strip()

        # Pusta linia
        if not stripped:
            close_list()
            close_table()
            continue

        # Pozioma kreska
        if RE_HR.match(stripped):
            close_list()
            close_table()
            html_lines.append("<hr>")
            continue

        # Obsługa tabeli Markdown
        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # Sprawdzenie czy to linia podziału |---|---|
            if all(RE_TABLE_DIVIDER.match(c) for c in cells if c):
                continue

            if not in_table:
                in_table = True
                html_lines.append('<div class="table-wrapper"><table><thead><tr>')
                html_lines.extend(f"<th>{html.escape(c)}</th>" for c in cells)
                html_lines.append("</tr></thead><tbody>")
            else:
                clean_first = RE_MARKDOWN_STRIP.sub('', cells[0]).strip().lower() if cells else ""
                is_pause_row = "przerw" in clean_first

                row_class = ' class="row-pause"' if is_pause_row else ''
                html_lines.append(f"<tr{row_class}>")
                for c in cells:
                    escaped = html.escape(c)
                    if is_pause_row:
                        # W wierszu przerwy usuwamy ewentualne gwiazdki/podkreślenia
                        html_lines.append(f"<td>{re.sub(r'[*_]', '', escaped).strip()}</td>")
                    else:
                        html_lines.append(f"<td>{_format_inline_markdown(escaped)}</td>")
                html_lines.append("</tr>")
            continue

        close_table()

        # Nagłówki (h1 - h4)
        m_heading = RE_HEADING.match(stripped)
        if m_heading:
            close_list()
            level = len(m_heading.group(1))
            html_lines.append(f"<h{level}>{html.escape(m_heading.group(2).strip())}</h{level}>")
            continue

        # Elementy listy (* lub -)
        if stripped.startswith(("* ", "- ")):
            if not in_list:
                in_list = True
                html_lines.append("<ul>")
            html_lines.append(f"<li>{_format_inline_markdown(html.escape(stripped[2:].strip()))}</li>")
            continue

        close_list()

        # Zwykły akapit
        html_lines.append(f"<p>{_format_inline_markdown(html.escape(stripped))}</p>")

    close_list()
    close_table()

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>{CSS_STYLES}</style>
</head>
<body>
  <div class="container">
    {chr(10).join(html_lines)}
  </div>
</body>
</html>"""


CSS_STYLES = """
    :root {
      --bg: #09090b;
      --card-bg: #121214;
      --border: #27272a;
      --border-subtle: #1c1c1f;
      --accent: #f4f4f5;
      --accent-muted: #a1a1aa;
      --text: #f4f4f5;
      --text-muted: #a1a1aa;
      --th-bg: #18181b;
      --tr-even: #0e0e10;
      --tr-odd: #141416;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      margin: 0;
      padding: 14px;
    }
    .container {
      max-width: 860px;
      margin: 0 auto;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px 22px;
      box-shadow: 0 12px 35px rgba(0, 0, 0, 0.85);
    }
    h1 { font-size: 1.4rem; color: #ffffff; margin-top: 6px; margin-bottom: 16px; border-bottom: 2px solid #3f3f46; padding-bottom: 8px; letter-spacing: -0.01em; }
    h2 { font-size: 1.2rem; color: #f4f4f5; margin-top: 26px; border-bottom: 1px solid var(--border); padding-bottom: 6px; letter-spacing: -0.01em; }
    h3 { font-size: 1.05rem; color: #e4e4e7; margin-top: 20px; margin-bottom: 8px; }
    h4 { font-size: 0.95rem; color: #d4d4d8; margin-top: 14px; margin-bottom: 6px; }
    p { margin: 8px 0; color: var(--text); }
    ul { margin: 8px 0; padding-left: 22px; }
    li { margin-bottom: 6px; color: var(--text-muted); }
    li strong, p strong { color: #ffffff; }
    hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
    .table-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 16px 0; border-radius: 8px; border: 1px solid var(--border); background: var(--card-bg); }
    table { width: 100%; border-collapse: collapse; font-size: 0.86rem; white-space: nowrap; }
    th { background: var(--th-bg); color: #ffffff; padding: 10px 12px; font-weight: 600; text-align: left; border-bottom: 2px solid var(--border); }
    td { padding: 9px 12px; border-bottom: 1px solid var(--border-subtle); color: var(--text); }
    tr:nth-child(even) { background: var(--tr-even); }
    tr:nth-child(odd) { background: var(--tr-odd); }
    tr:hover { background: rgba(255, 255, 255, 0.05); }
    tr.row-pause, tr.row-pause:nth-child(even), tr.row-pause:nth-child(odd) { background: rgba(0, 0, 0, 0.35) !important; }
    tr.row-pause td {
      color: #71717a !important;
      font-style: normal;
      border-bottom: 1px dashed var(--border-subtle);
    }
    tr.row-pause td em {
      font-style: normal;
      color: #71717a !important;
    }
    tr.row-pause:hover { background: rgba(255, 255, 255, 0.02) !important; }
"""
