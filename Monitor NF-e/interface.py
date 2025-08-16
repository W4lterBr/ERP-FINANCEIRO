# interface.py
# =============================================================================
# BOT – NF-e Browser (Flet)
# - Tipografia padronizada (UI_FONT_SIZE=9)
# - Topo fixo com cabeçalho "grudado" (sticky header) e colunas alinhadas
# - Ordenação por coluna (toggle ↑/↓ no clique)
# - Filtro principal por Número da NF; ENTER aplica filtros
# - Datas com máscara ao digitar (dd/mm/aaaa)
# - Drawer de certificados (selecionar tudo / adicionar .pfx)
# - Ações do Menu: Baixar por chave (diálogo), Executar Busca (com Consumo Indevido),
#                  Busca Completa, Atualizar Interface
# =============================================================================

import os
import sys
import re
import sqlite3
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

import flet as ft

# ---------------- Config visual global ----------------
UI_FONT_SIZE = 9
SCROLLBAR_WIDTH_GUESS = 16  # compensa a barra vertical p/ alinhar cabeçalho x corpo

# ---- PFX (opcional) ----------------------------------------------------------
try:
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except Exception:
    pkcs12 = None
    NameOID = None

# ---- helper p/ exibir alertas ------------------------------------------------
def show_alert(page: ft.Page, message: str, title: str = "Aviso"):
    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text(title, size=UI_FONT_SIZE),
        content=ft.Text(message, size=UI_FONT_SIZE),
        actions=[
            ft.TextButton(
                "OK",
                on_click=lambda e: setattr(dlg, "open", False),
                style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE)),
            )
        ],
    )
    page.dialog = dlg
    dlg.open = True
    try:
        page.update()
    except Exception:
        page.snack_bar = ft.SnackBar(content=ft.Text(message, size=UI_FONT_SIZE), open=True)
        page.update()

# ---- Constantes / Caminhos ----------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "notas.db"

CODIGOS_UF = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS",
    "50": "MS", "51": "MT", "52": "GO", "53": "DF"
}

COLUMNS = [
    "Ícone", "IE Tomador", "Nome", "CNPJ/CPF", "Num", "DtEmi",
    "Tipo", "Valor", "CFOP", "Vencimento", "Status", "UF", "Chave", "Natureza"
]

# Larguras por coluna (px) — ajuste à vontade
COL_WIDTHS = {
    "Ícone": 50,
    "IE Tomador": 90,
    "Nome": 260,
    "CNPJ/CPF": 120,
    "Num": 70,
    "DtEmi": 90,
    "Tipo": 50,
    "Valor": 110,
    "CFOP": 60,
    "Vencimento": 100,
    "Status": 260,
    "UF": 40,
    "Chave": 340,
    "Natureza": 260,
}
RIGHT_ALIGN = {"Valor"}
CENTER_ALIGN = {"Num", "CFOP", "UF", "Tipo", "DtEmi", "Vencimento"}

# ---- Utilidades ---------------------------------------------------------------
def only_digits(s: Optional[str]) -> str:
    return "".join(filter(str.isdigit, s or ""))

def brl_format(val: Any) -> str:
    try:
        if isinstance(val, str):
            if "R$" in val:
                return val
            val = float(val.replace(".", "").replace(",", "."))
        return f"R$ {float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val or "")

def parse_dt_emi(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        if "T" in raw:
            raw = raw.split("T", 1)[0]
        if "/" in raw and raw.count("/") == 2:
            return raw
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return raw

def format_cnpj(cnpj: str) -> str:
    d = only_digits(cnpj)
    if len(d) == 14:
        return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"
    if len(d) == 11:
        return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"
    return cnpj

def try_get_cn_from_pfx(path: str, password: str) -> str:
    try:
        if not pkcs12 or not NameOID:
            return ""
        data = Path(path).read_bytes()
        key, cert, _ = pkcs12.load_key_and_certificates(data, (password or "").encode())
        if cert is None:
            return ""
        for a in cert.subject:
            if a.oid == NameOID.COMMON_NAME:
                return str(a.value)
        return ""
    except Exception:
        return ""

def load_all_rows_from_db() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT * FROM notas_detalhadas")
        colnames = [d[0] for d in cur.description]
        for tup in cur.fetchall():
            rec = dict(zip(colnames, tup))

            nome_emit = rec.get("nome_emitente") or rec.get("nome") or ""
            cnpj_emit = rec.get("cnpj_emitente") or rec.get("cnpj_cpf") or ""
            valor = rec.get("valor")
            valor_fmt = brl_format(valor)

            status_original = (rec.get("status") or "").strip()
            st = status_original.lower()
            if ("cancelamento" in st or "cancelada" in st) and "135" in st:
                status_tratado = "Cancelada"
            else:
                status_tratado = status_original

            uf_codigo = str(rec.get("uf") or "").zfill(2)
            uf_sigla = CODIGOS_UF.get(uf_codigo, rec.get("uf") or "")

            chave = rec.get("chave") or ""
            if not chave or chave in seen:
                continue
            seen.add(chave)

            rows.append({
                "Ícone": "",
                "IE Tomador": rec.get("ie_tomador") or "",
                "Nome": nome_emit,
                "CNPJ/CPF": cnpj_emit,
                "Num": rec.get("numero") or "",
                "DtEmi": parse_dt_emi(rec.get("data_emissao")),
                "Tipo": rec.get("tipo") or "NFe",
                "Valor": valor_fmt,
                "CFOP": rec.get("cfop") or "",
                "Vencimento": rec.get("vencimento") or "",
                "Status": status_tratado,
                "UF": uf_sigla,
                "Chave": rec.get("chave") or "",
                "Natureza": rec.get("natureza") or "",
                "_CNPJ_DEST": rec.get("cnpj_destinatario") or "",
            })

    def key_dt(r):
        try:
            return datetime.strptime(r["DtEmi"], "%d/%m/%Y")
        except Exception:
            return datetime.min

    rows.sort(key=key_dt, reverse=True)
    return rows

def get_certificates_from_db() -> List[Dict[str, str]]:
    certs = []
    with sqlite3.connect(DB_PATH) as conn:
        for cnpj, caminho, senha, informante, cuf in conn.execute(
            "SELECT cnpj_cpf,caminho,senha,informante,cUF_autor FROM certificados"
        ).fetchall():
            certs.append({
                "cnpj": str(cnpj or ""), "informante": str(informante or ""),
                "caminho": str(caminho or ""), "senha": str(senha or ""), "cuf": str(cuf or ""),
            })
    return certs

def insert_certificate(cnpj: str, caminho: str, senha: str, informante: str, cuf: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM certificados WHERE informante=?", (informante,)).fetchone():
            return False
        cur.execute(
            "INSERT INTO certificados (cnpj_cpf,caminho,senha,informante,cUF_autor) VALUES (?,?,?,?,?)",
            (cnpj, caminho, senha, informante, cuf),
        )
        conn.commit()
        return True

# ---- Execução de scripts ------------------------------------------------------
def run_python_script(script_name: str, args: List[str] = None, cwd: Path = SCRIPT_DIR) -> int:
    if args is None:
        args = []
    cmd = [sys.executable, str(cwd / script_name), *args]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
        )
        for line in proc.stdout:
            print(line, end="")
        proc.wait()
        return proc.returncode
    except Exception as e:
        print(f"[ERRO] Falha ao executar {script_name}: {e}")
        return -1

def stream_python_script(script_name: str, args: List[str], on_line, stop_predicate=None, cwd: Path = SCRIPT_DIR) -> int:
    cmd = [sys.executable, str(cwd / script_name), *args]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
        )
        stop = False
        for line in proc.stdout:
            print(line, end="")
            if on_line:
                on_line(line)
            if stop_predicate and stop_predicate(line):
                stop = True
                break
        if stop:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return proc.returncode if proc.returncode is not None else 0
    except Exception as e:
        print(f"[ERRO] Falha ao executar {script_name}: {e}")
        return -1

# ---- App Flet -----------------------------------------------------------------
def main(page: ft.Page):
    page.title = "BOT – NF-e Browser (Flet)"
    page.window_width = 1280
    page.window_height = 800
    page.theme_mode = "light"
    page.padding = 12

    all_rows: List[Dict[str, Any]] = []
    filtered_rows: List[Dict[str, Any]] = []
    selected_certs: Dict[str, ft.Checkbox] = {}
    current_sort_col: Optional[int] = None
    current_sort_asc: bool = True

    status = ft.Text("", weight=ft.FontWeight.BOLD, size=UI_FONT_SIZE)
    def set_status(msg: str, color: str = "#37506c"):
        status.value = msg
        status.color = color
        status.update()

    # ------------------- Filtros -------------------
    def mask_date_on_change(tf: ft.TextField):
        raw = only_digits(tf.value or "")[:8]
        if len(raw) >= 5:
            tf.value = f"{raw[:2]}/{raw[2:4]}/{raw[4:]}"
        elif len(raw) >= 3:
            tf.value = f"{raw[:2]}/{raw[2:]}"
        else:
            tf.value = raw
        try:
            tf.update()
        except Exception:
            pass

    tf_num = ft.TextField(
        label="Número da NF",
        width=200, height=32,
        text_size=UI_FONT_SIZE, label_style=ft.TextStyle(size=UI_FONT_SIZE),
        keyboard_type=ft.KeyboardType.NUMBER,
        on_submit=lambda e: apply_filters(),   # ENTER -> aplica
    )
    dp_ini = ft.TextField(
        label="Dt Início (dd/mm/aaaa)",
        width=120, height=32,
        text_size=UI_FONT_SIZE, label_style=ft.TextStyle(size=UI_FONT_SIZE),
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=lambda e: mask_date_on_change(e.control),
        on_submit=lambda e: apply_filters(),   # ENTER -> aplica
    )
    dp_fim = ft.TextField(
        label="Dt Fim (dd/mm/aaaa)",
        width=120, height=32,
        text_size=UI_FONT_SIZE, label_style=ft.TextStyle(size=UI_FONT_SIZE),
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=lambda e: mask_date_on_change(e.control),
        on_submit=lambda e: apply_filters(),   # ENTER -> aplica
    )

    # ---------- Ordenação ----------
    def _parse_date_ddmmyyyy(s: str) -> datetime:
        try:
            return datetime.strptime(s, "%d/%m/%Y")
        except Exception:
            return datetime.min

    def _parse_brl(s: str) -> float:
        try:
            s = (s or "").replace("R$", "").strip().replace(".", "").replace(",", ".")
            return float(s)
        except Exception:
            return 0.0

    def _sort_key(row: Dict[str, Any], col_name: str):
        v = row.get(col_name)
        if col_name in ("DtEmi", "Vencimento"): return _parse_date_ddmmyyyy(str(v))
        if col_name in ("Valor",): return _parse_brl(str(v))
        if col_name in ("Num", "CFOP"):
            try: return int(str(v))
            except Exception: return 0
        if col_name in ("CNPJ/CPF", "IE Tomador", "Chave"):
            try: return int(only_digits(str(v)))
            except Exception: return 0
        return str(v or "").strip().lower()

    def _apply_sort(col_index: int, asc: bool):
        nonlocal current_sort_col, current_sort_asc, filtered_rows
        current_sort_col, current_sort_asc = col_index, asc
        col_name = COLUMNS[col_index]
        filtered_rows.sort(key=lambda r: _sort_key(r, col_name), reverse=not asc)
        try:
            body_table.sort_column_index = col_index
            body_table.sort_ascending = asc
            header_table.sort_column_index = col_index
            header_table.sort_ascending = asc
        except Exception:
            pass
        refresh_table()

    # ------------------- Tabela com cabeçalho fixo -------------------
    def _header_label(name: str) -> ft.Container:
        align = ft.alignment.center_left
        if name in RIGHT_ALIGN:
            align = ft.alignment.center_right
        elif name in CENTER_ALIGN:
            align = ft.alignment.center
        return ft.Container(
            width=COL_WIDTHS[name],
            alignment=align,
            content=ft.Text(name, size=UI_FONT_SIZE),
        )

    def _make_columns():
        cols = []
        for idx, name in enumerate(COLUMNS):
            def _on_sort(ev, i=idx):
                asc = getattr(ev, "ascending", None)
                if asc is None:
                    asc = not (body_table.sort_column_index == i and getattr(body_table, "sort_ascending", True))
                _apply_sort(i, asc)
            try:
                cols.append(ft.DataColumn(_header_label(name), on_sort=_on_sort))
            except TypeError:
                # fallback para versões antigas do Flet
                btn = ft.TextButton(
                    text=name,
                    style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE)),
                    on_click=lambda e, i=idx: _apply_sort(i, not (body_table.sort_column_index == i and getattr(body_table, "sort_ascending", True))),
                )
                cols.append(ft.DataColumn(ft.Container(width=COL_WIDTHS[name], content=btn)))
        return cols

    header_table = ft.DataTable(columns=[], rows=[], heading_row_height=32, data_row_max_height=0, column_spacing=6)
    body_table   = ft.DataTable(columns=[], rows=[], heading_row_height=0,  data_row_max_height=32, column_spacing=6)
    header_table.columns = _make_columns()
    body_table.columns   = _make_columns()

    def _txt_cell(value: Any, col_name: str) -> ft.Container:
        try:
            ov = ft.TextOverflow.ELLIPSIS
        except Exception:
            ov = None
        align = ft.alignment.center_left
        if col_name in RIGHT_ALIGN:
            align = ft.alignment.center_right
        elif col_name in CENTER_ALIGN:
            align = ft.alignment.center
        return ft.Container(
            width=COL_WIDTHS[col_name],
            alignment=align,
            padding=ft.padding.symmetric(vertical=4),
            content=ft.Text(str(value), size=UI_FONT_SIZE, no_wrap=True, max_lines=1, overflow=ov),
        )

    def refresh_table():
        body_table.rows.clear()
        for r in filtered_rows:
            icon = ""
            st = (r.get("Status") or "").lower()
            if "confirmação da operação" in st and "135" in st:
                icon = "XML"
            elif "cancelada" in st:
                icon = "X"
            vals = [icon if col == "Ícone" else r.get(col, "") for col in COLUMNS]
            cells = [ft.DataCell(_txt_cell(vals[i], COLUMNS[i])) for i in range(len(COLUMNS))]
            body_table.rows.append(ft.DataRow(cells=cells))
        body_table.update()

    # -------- Drawer (certificados) --------
    certs_col = ft.Column(spacing=4, scroll=ft.ScrollMode.ALWAYS)

    def load_certs():
        selected_certs.clear()
        certs_col.controls.clear()
        certs = get_certificates_from_db()
        if not certs:
            certs_col.controls.append(ft.Text("Nenhum certificado cadastrado.", italic=True, size=UI_FONT_SIZE))
        else:
            for cert in certs:
                cnpj = cert.get("cnpj", "") or cert.get("informante", "")
                cn = try_get_cn_from_pfx(cert.get("caminho", ""), cert.get("senha", "")) or cert.get("informante", "")
                label_txt = f"{cn}  •  {format_cnpj(cnpj)}"
                cb = ft.Checkbox(value=True, on_change=lambda e: apply_filters())
                certs_col.controls.append(ft.Row([cb, ft.Text(label_txt, size=UI_FONT_SIZE)], spacing=6))
                selected_certs[cert.get("informante", "")] = cb
        try:
            if getattr(certs_col, "page", None):
                certs_col.update()
        except Exception:
            pass
        page.update()

    cb_select_all = ft.Checkbox(value=True, on_change=lambda e: on_select_all_change())
    def on_select_all_change():
        v = cb_select_all.value
        for cb in selected_certs.values():
            cb.value = v
        apply_filters()
        try:
            if getattr(certs_col, "page", None):
                certs_col.update()
        except Exception:
            pass

    def add_certificate_dialog(e=None):
        if pkcs12 is None:
            return show_alert(page, "Instale 'cryptography' para adicionar o certificado (pip install cryptography).")

        def on_file_result(res: ft.FilePickerResultEvent):
            if not res.files:
                return
            file_path = res.files[0].path

            tf_senha = ft.TextField(
                label="Senha do certificado (.pfx)",
                password=True, can_reveal_password=True,
                width=300, text_size=UI_FONT_SIZE, label_style=ft.TextStyle(size=UI_FONT_SIZE)
            )
            dd_uf = ft.Dropdown(
                label="UF (código numérico)", width=200,
                options=[ft.dropdown.Option(k) for k in sorted(CODIGOS_UF.keys())],
                value="50", text_size=UI_FONT_SIZE,
            )

            def salvar_cert(_e=None):
                senha = tf_senha.value or ""
                uf = dd_uf.value or ""
                try:
                    data = Path(file_path).read_bytes()
                    key, cert, _ = pkcs12.load_key_and_certificates(data, senha.encode())
                    if cert is None:
                        show_alert(page, "Não foi possível ler o certificado.")
                        return
                    cn = next(a.value for a in cert.subject if a.oid == NameOID.COMMON_NAME)
                    digits = only_digits(cn) or only_digits(cert.subject.rfc4514_string())
                    informante = digits
                    cnpj = digits
                    ok = insert_certificate(cnpj=cnpj, caminho=file_path, senha=senha, informante=informante, cuf=uf)
                    if ok:
                        set_status("Certificado salvo com sucesso.", "#2e7d32")
                        load_certs()
                        dlg.open = False
                        page.update()
                    else:
                        show_alert(page, "Certificado já cadastrado para este informante.")
                except Exception as ex:
                    show_alert(page, f"Falha ao ler/salvar certificado:\n{ex}")

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Adicionar Certificado", size=UI_FONT_SIZE),
                content=ft.Column([ft.Text(file_path, selectable=True, size=UI_FONT_SIZE), tf_senha, dd_uf], tight=True),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda _e: setattr(dlg, "open", False),
                                  style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE))),
                    ft.ElevatedButton("Salvar", on_click=salvar_cert,
                                      style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE))),
                ],
            )
            page.dialog = dlg
            dlg.open = True
            page.update()

        fp = ft.FilePicker(on_result=on_file_result)
        page.overlay.append(fp)
        page.update()
        fp.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pfx"])

    drawer_body = ft.Container(
        content=ft.Column(
            [
                ft.Row([cb_select_all, ft.Text("Selecionar tudo", size=UI_FONT_SIZE)], spacing=6),
                ft.Divider(),
                ft.Container(content=certs_col, height=400),
                ft.Divider(),
                ft.Row(
                    [
                        ft.ElevatedButton("Adicionar Certificado",
                                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE)),
                                          on_click=add_certificate_dialog),
                        ft.ElevatedButton("Aplicar filtros",
                                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE)),
                                          on_click=lambda e: apply_filters()),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            tight=True,
        ),
        width=320,
        padding=10,
    )
    page.drawer = ft.NavigationDrawer(controls=[drawer_body])

    def open_certs_drawer(e=None):
        try:
            if hasattr(page, "open_drawer"):
                page.open_drawer()
                return
        except Exception:
            pass
        try:
            if getattr(page, "drawer", None):
                page.drawer.open = True
                page.update()
        except Exception:
            pass

    # ------------------- Carregar/Filtrar -------------------
    def reload_all(e=None):
        nonlocal all_rows
        try:
            all_rows = load_all_rows_from_db()
            apply_filters()
        except Exception as ex:
            set_status(f"Erro ao carregar dados: {ex}", "#a94442")

    def apply_filters(e=None):
        nonlocal filtered_rows
        nf_num = (tf_num.value or "").strip()
        try:
            d_ini = datetime.strptime((dp_ini.value or "").strip(), "%d/%m/%Y").date() if dp_ini.value else None
        except Exception:
            d_ini = None
        try:
            d_fim = datetime.strptime((dp_fim.value or "").strip(), "%d/%m/%Y").date() if dp_fim.value else None
        except Exception:
            d_fim = None

        checked = [inf for inf, cb in selected_certs.items() if cb.value]
        checked_digits = [only_digits(x) for x in checked]

        def in_range(dstr: str) -> bool:
            try:
                d = datetime.strptime(dstr, "%d/%m/%Y").date()
                if d_ini and d < d_ini:
                    return False
                if d_fim and d > d_fim:
                    return False
                return True
            except Exception:
                return False if (d_ini or d_fim) else True

        def match_any_cnpj(rec: Dict[str, Any]) -> bool:
            emit = only_digits(rec.get("CNPJ/CPF"))
            dest = only_digits(rec.get("_CNPJ_DEST"))
            return (emit in checked_digits) or (dest in checked_digits)

        base = all_rows if not checked_digits else [r for r in all_rows if match_any_cnpj(r)]

        if nf_num:
            nf_num_digits = only_digits(nf_num)
            base = [r for r in base if nf_num_digits in only_digits(str(r.get("Num", "")))]

        filtered_rows = [r for r in base if in_range(r.get("DtEmi", ""))]

        if current_sort_col is not None:
            _apply_sort(current_sort_col, current_sort_asc)
        else:
            refresh_table()
        set_status(f"{len(filtered_rows)} notas exibidas.")

    # ------------------- Ações/buscas -------------------
    def run_search_async(script: str, args: List[str] = None, post_msg: str = ""):
        def worker():
            set_status(f"Executando {script}...", "#37506c")
            code = run_python_script(script, args or [])
            if code == 0:
                set_status(post_msg or "Concluído.", "#2e7d32")
                reload_all()
            else:
                set_status(f"Erro ao executar {script}. Veja o terminal.", "#a94442")
        threading.Thread(target=worker, daemon=True).start()

    def buscar_normal(e=None):
        def worker():
            set_status("Executando nfe_search.py...", "#37506c")
            last_nsu = None
            consumo_detectado = False

            def on_line(line: str):
                nonlocal last_nsu
                m = re.search(r"ultNSU>(\d+)<", line)
                if m:
                    last_nsu = m.group(1)

            def stop_predicate(line: str) -> bool:
                nonlocal consumo_detectado
                t = line.strip()
                if ("Rejeicao: Consumo Indevido" in t) or ("consumo indevido" in t.lower()) or ("Dormindo por 60 minutos" in t):
                    consumo_detectado = True
                    return True
                return False

            _ = stream_python_script("nfe_search.py", [], on_line=on_line, stop_predicate=stop_predicate)
            if consumo_detectado:
                msg = "SEFAZ: Rejeição — Consumo Indevido. Tente novamente após 1 hora."
                if last_nsu:
                    msg += f" (ultNSU: {last_nsu})"
                page.snack_bar = ft.SnackBar(content=ft.Text(msg, size=UI_FONT_SIZE), open=True)
                page.update()
                set_status(msg, "#e65100")
                return
            set_status("Busca concluída. Atualizando dados...", "#2e7d32")
            reload_all()
        threading.Thread(target=worker, daemon=True).start()

    def buscar_completa(e=None):
        run_search_async("DownloadAllXmls.py", [], "Busca Completa concluída. Atualizando dados...")

    def baixar_por_chave(e=None):
        # diálogo para informar a chave (Enter confirma)
        tf_chave = ft.TextField(
            label="Chave (44 dígitos)", width=320,
            text_size=UI_FONT_SIZE, label_style=ft.TextStyle(size=UI_FONT_SIZE),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        def ok(_e=None):
            key = (tf_chave.value or "").strip()
            if len(key) != 44 or not key.isdigit():
                show_alert(page, "Informe a chave com 44 dígitos.")
                return
            dlg.open = False
            page.update()
            run_search_async("nfe_search.py", ["--chave", key], "Busca por chave concluída. Atualizando dados...")
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Baixar por chave", size=UI_FONT_SIZE),
            content=tf_chave,
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _e: setattr(dlg, "open", False),
                              style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE))),
                ft.ElevatedButton("OK", on_click=ok,
                                  style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE))),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()
        tf_chave.on_submit = lambda _e: ok()

    # ------------------- Layout topo fixo + sticky header -------------------
    menu_popup = ft.PopupMenuButton(
        items=[
            ft.PopupMenuItem(content=ft.Text("Selecionar CNPJ (Certificados)", size=UI_FONT_SIZE), on_click=open_certs_drawer),
            ft.PopupMenuItem(content=ft.Text("Baixar por chave", size=UI_FONT_SIZE), on_click=baixar_por_chave),
            ft.PopupMenuItem(content=ft.Text("Executar Busca", size=UI_FONT_SIZE), on_click=buscar_normal),
            ft.PopupMenuItem(content=ft.Text("Busca Completa", size=UI_FONT_SIZE), on_click=buscar_completa),
            ft.PopupMenuItem(content=ft.Text("Atualizar Interface", size=UI_FONT_SIZE), on_click=reload_all),
        ],
        content=ft.Container(content=ft.Text("Menu", size=UI_FONT_SIZE), padding=10, border_radius=6, bgcolor="#F5F5F5"),
    )

    filtros_row = ft.Row(
        [
            tf_num, dp_ini, dp_fim,
            ft.ElevatedButton(
                "Aplicar filtros", height=32,
                style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_FONT_SIZE)),
                on_click=lambda e: apply_filters(),  # BOTÃO -> aplica
            ),
        ],
        spacing=8,
        alignment=ft.MainAxisAlignment.END,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    top_bar = ft.Row(
        [menu_popup, ft.Container(expand=1), filtros_row],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # Rolagem horizontal compartilhada; vertical só no corpo
    horizontal_scroller = ft.Row(
        controls=[
            ft.Column(
                controls=[
                    ft.Container(header_table, padding=ft.padding.only(right=SCROLLBAR_WIDTH_GUESS)),
                    ft.Container(content=ft.Column([body_table], expand=True, scroll=ft.ScrollMode.ALWAYS), expand=True),
                ],
                expand=True,
                spacing=0,
            )
        ],
        expand=True,
        scroll=ft.ScrollMode.ALWAYS,
    )

    layout = ft.Column([top_bar, horizontal_scroller, ft.Divider(), status], expand=True, spacing=8)
    page.add(layout)

    # Inicialização
    load_certs()
    all_rows[:] = load_all_rows_from_db()
    apply_filters()
    set_status("Pronto. Cabeçalho alinhado e fixo. ENTER aplica filtros. Menu para executar ações.")
    

if __name__ == "__main__":
    ft.app(target=main)
