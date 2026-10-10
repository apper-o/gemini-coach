import re
import html


RE_HR = re.compile(r'^(?:-{3,}|={3,})$')
RE_TABLE_DIVIDER = re.compile(r'^:?-+:?$')
RE_BOLD = re.compile(r'\*\*(.*?)\*\*')
RE_ITALIC_STAR = re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)')
RE_ITALIC_UNDERSCORE = re.compile(r'(?<!_)_([^_]+)_(?!_)')


def _format_inline_markdown(text):
    """Konwertuje pogrubienie oraz kursywę Markdown na tagi HTML."""
    text = RE_BOLD.sub(r'<strong>\1</strong>', text)
    text = RE_ITALIC_STAR.sub(r'<em>\1</em>', text)
    text = RE_ITALIC_UNDERSCORE.sub(r'<em>\1</em>', text)
    return text


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
    lines = md_text.splitlines()
    html_lines = []
    in_table = False
    in_list = False
    table_has_header = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def close_table():
        nonlocal in_table, table_has_header
        if in_table:
            html_lines.append("</tbody></table></div>")
            in_table = False
            table_has_header = False

    for line in lines:
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
                html_lines.append('<div class="table-wrapper"><table>')
                html_lines.append("<thead><tr>")
                for c in cells:
                    html_lines.append(f"<th>{html.escape(c)}</th>")
                html_lines.append("</tr></thead><tbody>")
                table_has_header = True
            else:
                first_cell_raw = cells[0] if cells else ""
                clean_first = re.sub(r'[*_`]', '', first_cell_raw).strip().lower()
                is_pause_row = clean_first.startswith("przerw") or "przerwa" in clean_first

                row_class = ' class="row-pause"' if is_pause_row else ''
                html_lines.append(f"<tr{row_class}>")
                for c in cells:
                    cell_html = html.escape(c)
                    if is_pause_row:
                        # W wierszu przerwy usuwamy ewentualne ** (pogrubienia) oraz gwiazdki/podkreślenia
                        cell_clean = re.sub(r'\*\*(.*?)\*\*', r'\1', cell_html)
                        cell_clean = re.sub(r'[*_]', '', cell_clean).strip()
                        html_lines.append(f"<td>{cell_clean}</td>")
                    else:
                        cell_html = _format_inline_markdown(cell_html)
                        html_lines.append(f"<td>{cell_html}</td>")
                html_lines.append("</tr>")
            continue
        else:
            close_table()

        # Nagłówki
        if stripped.startswith("#### "):
            close_list()
            h_text = html.escape(stripped[5:].strip())
            html_lines.append(f"<h4>{h_text}</h4>")
            continue
        elif stripped.startswith("### "):
            close_list()
            h_text = html.escape(stripped[4:].strip())
            html_lines.append(f"<h3>{h_text}</h3>")
            continue
        elif stripped.startswith("## "):
            close_list()
            h_text = html.escape(stripped[3:].strip())
            html_lines.append(f"<h2>{h_text}</h2>")
            continue
        elif stripped.startswith("# "):
            close_list()
            h_text = html.escape(stripped[2:].strip())
            html_lines.append(f"<h1>{h_text}</h1>")
            continue

        # Elementy listy (* lub -)
        if stripped.startswith("* ") or stripped.startswith("- "):
            if not in_list:
                in_list = True
                html_lines.append("<ul>")
            item_text = html.escape(stripped[2:].strip())
            item_text = _format_inline_markdown(item_text)
            html_lines.append(f"<li>{item_text}</li>")
            continue
        else:
            close_list()

        # Zwykły akapit
        p_text = html.escape(stripped)
        p_text = _format_inline_markdown(p_text)
        html_lines.append(f"<p>{p_text}</p>")

    close_list()
    close_table()

    body_content = "\n".join(html_lines)

    css = """
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

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head>
<body>
  <div class="container">
    {body_content}
  </div>
</body>
</html>"""
