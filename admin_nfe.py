# admin_nfe.py
# =============================================================================
# CRUD para notas_detalhadas (SQLite) com interface Flet.
# Ajustes importantes:
#   • Descoberta automática do DB com dados (varre subpastas, escolhe o que
#     tiver mais linhas em notas_detalhadas).
#   • Botão "Trocar banco..." (FilePicker) e "Detectar banco automaticamente".
#   • NÃO cria a tabela automaticamente ao abrir (evita tabela vazia no DB errado).
#   • Se a tabela não existir, mostra aviso e oferece botão "Criar tabela".
#   • Restante: filtros, ordenação, paginação, edição, exclusão e logs.
# =============================================================================

from __future__ import annotations
import os, sys, sqlite3, logging
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Any, Optional

import flet as ft

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ADMIN-NFE")

# ---------------- Flet shims -------------
def _COLORS():
    return ft.colors if hasattr(ft, "colors") else ft.Colors
def _ICONS():
    return ft.icons if hasattr(ft, "icons") else getattr(ft, "Icons", None)
C = _COLORS()
IC = _ICONS()
def ICON(name: str, fallback: str):
    return getattr(IC, name, fallback) if IC else fallback
try:
    SM_ALWAYS = ft.ScrollMode.ALWAYS
    SM_AUTO = ft.ScrollMode.AUTO
except Exception:
    SM_ALWAYS, SM_AUTO = "always", "auto"

UI_SIZE   = 9
ROW_H     = 32
HEAD_H    = 32
SCROLLBAR = 16

# ---------------- Colunas Grid ------------
COLUMNS = [
    "Ícone", "IE Tomador", "Nome", "CNPJ/CPF", "Num", "DtEmi",
    "Tipo", "Valor", "CFOP", "Vencimento", "Status", "UF", "Chave", "Natureza"
]
COL_W = {
    "Ícone": 46, "IE Tomador": 96, "Nome": 260, "CNPJ/CPF": 120, "Num": 70,
    "DtEmi": 92, "Tipo": 50, "Valor": 110, "CFOP": 60, "Vencimento": 100,
    "Status": 260, "UF": 44, "Chave": 340, "Natureza": 260
}
RIGHT_ALIGN  = {"Valor"}
CENTER_ALIGN = {"Num", "CFOP", "DtEmi", "Vencimento", "UF", "Tipo"}

TOTAL_W = sum(COL_W.values()) + 40

# ---------------- Utils -------------------
def only_digits(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def parse_dt_emi(s: str) -> str:
    if not s: return ""
    try:
        if "T" in s: s = s.split("T", 1)[0]
        if "/" in s: return s
        return datetime.fromisoformat(s).strftime("%d/%m/%Y")
    except Exception:
        return s

def validate_ddmmyyyy(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        return None

# ---------------- DB helpers --------------
def count_rows_in_db(db_path: Path) -> int:
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notas_detalhadas'")
            if not cur.fetchone():
                return -1  # tabela não existe
            cur = conn.execute("SELECT COUNT(*) FROM notas_detalhadas")
            n = cur.fetchone()[0]
            return int(n)
    except Exception as e:
        log.debug(f"count_rows_in_db({db_path}): {e}")
        return -1

def scan_for_best_db(start_dir: Path) -> Optional[Path]:
    """
    Procura por 'notas.db' do diretório atual para baixo (profundidade 2)
    e também irmãos prováveis. Escolhe o que tiver MAIS LINHAS em notas_detalhadas.
    """
    candidates: List[Path] = []
    # 1) env
    env = os.getenv("MONITOR_NFE_DB")
    if env:
        p = Path(env)
        if p.exists():
            candidates.append(p)
            log.debug(f"[SCAN] env candidate: {p}")

    # 2) locais prováveis
    script_dir = start_dir
    likely = [
        script_dir / "notas.db",
        script_dir / "Monitor NF-e" / "notas.db",
        script_dir.parent / "notas.db",
        script_dir.parent / "Monitor NF-e" / "notas.db",
    ]
    for p in likely:
        if p.exists(): candidates.append(p)

    # 3) varredura rasa em subpastas (profundidade 2)
    for child in script_dir.iterdir():
        if child.is_dir():
            p = child / "notas.db"
            if p.exists(): candidates.append(p)
            # um nível abaixo
            for sub in child.iterdir():
                if sub.is_dir():
                    p2 = sub / "notas.db"
                    if p2.exists(): candidates.append(p2)

    # remove duplicados preservando ordem
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            uniq.append(c); seen.add(c)

    if not uniq:
        return None

    # rankear por contagem
    best = None
    best_rows = -2
    for c in uniq:
        rows = count_rows_in_db(c)
        log.debug(f"[SCAN] {c} -> rows={rows}")
        if rows > best_rows:
            best_rows = rows
            best = c

    return best

# ---------------- DB access ---------------
class DB:
    def __init__(self, path: Path, create_table: bool = False):
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._cols = None
        # Só cria tabela se explicitamente pedido
        if create_table:
            self.ensure_table()

    def close(self):
        try: self.conn.close()
        except Exception: pass

    def table_exists(self) -> bool:
        cur = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notas_detalhadas'")
        return cur.fetchone() is not None

    def ensure_table(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS notas_detalhadas (
            chave TEXT PRIMARY KEY,
            ie_tomador TEXT,
            nome_emitente TEXT,
            cnpj_emitente TEXT,
            numero TEXT,
            data_emissao TEXT,
            tipo TEXT,
            valor TEXT,
            cfop TEXT,
            vencimento TEXT,
            uf TEXT,
            natureza TEXT,
            status TEXT,
            atualizado_em TEXT,
            cnpj_destinatario TEXT,
            nome_destinatario TEXT,
            cnpj_cpf TEXT,
            nome TEXT
        )""")
        self.conn.commit()

    def cols(self) -> List[str]:
        if self._cols is None:
            if not self.table_exists():
                self._cols = []
            else:
                cur = self.conn.execute("PRAGMA table_info(notas_detalhadas)")
                self._cols = [r[1] for r in cur.fetchall()]
            log.debug(f"[DB cols] {self._cols}")
        return self._cols

    def fetch_all(self) -> List[Dict[str, Any]]:
        if not self.table_exists():
            return []
        cur = self.conn.execute("SELECT * FROM notas_detalhadas")
        return [dict(r) for r in cur.fetchall()]

    def get_by_chave(self, chave: str) -> Optional[Dict[str, Any]]:
        if not self.table_exists():
            return None
        cur = self.conn.execute("SELECT * FROM notas_detalhadas WHERE chave=?", (chave,))
        r = cur.fetchone()
        return dict(r) if r else None

    def upsert(self, rec: Dict[str, Any]):
        if not self.table_exists():
            raise RuntimeError("Tabela 'notas_detalhadas' não existe neste banco.")
        cols_db = set(self.cols())
        data = {k: v for k, v in rec.items() if k in cols_db}
        if not data.get("chave"):
            raise ValueError("Informe a 'chave' (44 dígitos).")
        data["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur = self.conn.execute("SELECT ie_tomador FROM notas_detalhadas WHERE chave=?", (data["chave"],))
        row = cur.fetchone()
        exists = row is not None
        if exists and (not (data.get("ie_tomador") or "").strip()):
            data.pop("ie_tomador", None)  # preserva IE

        cols = list(data.keys())
        vals = [data[c] for c in cols]
        if exists:
            sets = ", ".join([f"{c}=?" for c in cols if c != "chave"])
            q = f"UPDATE notas_detalhadas SET {sets} WHERE chave=?"
            self.conn.execute(q, [data[c] for c in cols if c != "chave"] + [data["chave"]])
            log.debug(f"[UPDATE] {data['chave']}")
        else:
            q = f"INSERT INTO notas_detalhadas ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
            self.conn.execute(q, vals)
            log.debug(f"[INSERT] {data['chave']}")
        self.conn.commit()

    def delete(self, chave: str):
        if not self.table_exists():
            raise RuntimeError("Tabela 'notas_detalhadas' não existe neste banco.")
        self.conn.execute("DELETE FROM notas_detalhadas WHERE chave=?", (chave,))
        self.conn.commit()
        log.debug(f"[DELETE] {chave}")

# ---------------- App ----------------------
def main(page: ft.Page):
    page.title = "Admin • NF-e (SQLite)"
    page.window_width = 1280
    page.window_height = 800
    page.padding = 12
    try: page.scroll = None
    except Exception: pass

    # ---- DB detection ----
    script_dir = Path(__file__).parent.resolve()
    auto_db = scan_for_best_db(script_dir)
    if auto_db:
        db_path = auto_db
    else:
        # último recurso: MONITOR_NFE_DB ou ./notas.db
        env = os.getenv("MONITOR_NFE_DB")
        db_path = Path(env) if env else (script_dir / "notas.db")

    # UI state
    db: DB = DB(db_path, create_table=False)
    current_db_txt = ft.Text(f"Banco atual: {db.path}", size=UI_SIZE)

    # FilePicker
    def on_pick_db(e: ft.FilePickerResultEvent):
        nonlocal db
        if not e.files: return
        new_path = Path(e.files[0].path)
        try:
            db.close()
        except Exception:
            pass
        db = DB(new_path, create_table=False)
        current_db_txt.value = f"Banco atual: {db.path}"
        current_db_txt.update()
        dlog(f"[DB] Trocado para {new_path}")
        reload_all()

    fp = ft.FilePicker(on_result=on_pick_db)
    page.overlay.append(fp)

    # Botões de DB
    def choose_db(_=None):
        fp.pick_files(allow_multiple=False, allowed_extensions=["db","sqlite","sqlite3"], file_type=ft.FilePickerFileType.CUSTOM)

    def auto_detect_db(_=None):
        nonlocal db
        best = scan_for_best_db(script_dir)
        if not best:
            show_alert("Nenhum notas.db encontrado com a tabela 'notas_detalhadas'.")
            return
        try:
            db.close()
        except Exception:
            pass
        db = DB(best, create_table=False)
        current_db_txt.value = f"Banco atual: {db.path}"
        current_db_txt.update()
        dlog(f"[DB] Detectado automaticamente: {best}")
        reload_all()

    # Criar tabela (quando faltar)
    def create_table_now(_=None):
        try:
            db.ensure_table()
            dlog("[DB] Tabela 'notas_detalhadas' criada.")
            reload_all()
        except Exception as ex:
            show_alert(f"Erro ao criar tabela: {ex}")

    # --- Estado grid ---
    all_rows: List[Dict[str, Any]] = []
    filtered: List[Dict[str, Any]] = []
    current_page = 1
    page_size = 100
    sort_col: Optional[int] = None
    sort_asc = True
    selection_chave: Optional[str] = None

    # --- Log UI ---
    log_lv = ft.ListView(height=120, spacing=2, auto_scroll=True)
    def dlog(msg: str):
        print(msg)
        log_lv.controls.append(ft.Text(msg, size=UI_SIZE))
        try: log_lv.update()
        except Exception: pass

    def show_alert(msg: str):
        page.snack_bar = ft.SnackBar(content=ft.Text(msg, size=UI_SIZE), open=True)
        page.update()

    # --- Filtros ---
    def mask_date(tf: ft.TextField):
        raw = only_digits(tf.value)[:8]
        tf.value = raw if len(raw)<3 else (f"{raw[:2]}/{raw[2:]}" if len(raw)<5 else f"{raw[:2]}/{raw[2:4]}/{raw[4:]}")
        tf.update()

    tf_num = ft.TextField(label="Número", width=120, height=32,
                          text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                          keyboard_type=ft.KeyboardType.NUMBER,
                          on_submit=lambda e: apply_filters())
    tf_chave = ft.TextField(label="Chave (44)", width=240, height=32,
                            text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                            keyboard_type=ft.KeyboardType.NUMBER,
                            on_submit=lambda e: apply_filters())
    tf_nome = ft.TextField(label="Nome contém", width=220, height=32,
                           text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                           on_submit=lambda e: apply_filters())
    dt_ini = ft.TextField(label="Dt Início", width=120, height=32,
                          text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                          keyboard_type=ft.KeyboardType.NUMBER,
                          on_change=lambda e: mask_date(e.control),
                          on_submit=lambda e: apply_filters())
    dt_fim = ft.TextField(label="Dt Fim", width=120, height=32,
                          text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                          keyboard_type=ft.KeyboardType.NUMBER,
                          on_change=lambda e: mask_date(e.control),
                          on_submit=lambda e: apply_filters())

    status = ft.Text("", size=UI_SIZE, weight=ft.FontWeight.BOLD)
    def set_status(s: str, color=None):
        status.value = s
        status.color = color or None
        try: status.update()
        except Exception: pass
        dlog(f"[STATUS] {s}")

    # --- Ordenação ---
    def key_conv(row: Dict[str, Any], col: str):
        v = row.get(col)
        if col in ("DtEmi", "Vencimento"):
            try: return datetime.strptime(str(v), "%d/%m/%Y")
            except: return datetime.min
        if col=="Valor":
            try:
                s = str(v).replace("R$","").strip().replace(".","").replace(",",".")
                return float(s)
            except: return 0.0
        if col in ("Num","CFOP"):
            try: return int(str(v))
            except: return 0
        if col in ("CNPJ/CPF","IE Tomador","Chave"):
            try: return int(only_digits(str(v)))
            except: return 0
        return str(v or "").lower()

    def apply_sort(idx: int):
        nonlocal sort_col, sort_asc, filtered, current_page
        col = COLUMNS[idx]
        sort_asc = not (sort_col==idx and sort_asc)
        sort_col = idx
        filtered.sort(key=lambda r: key_conv(r, col), reverse=not sort_asc)
        current_page = 1
        refresh_table()

    # --- Tabelas ---
    try: OV = ft.TextOverflow.ELLIPSIS
    except Exception: OV = None
    def cell(val, col):
        align = ft.alignment.center_left
        if col in RIGHT_ALIGN: align=ft.alignment.center_right
        elif col in CENTER_ALIGN: align=ft.alignment.center
        return ft.Container(
            width=COL_W[col], alignment=align,
            padding=ft.padding.symmetric(vertical=4),
            content=ft.Text(str(val or ""), size=UI_SIZE, no_wrap=True, overflow=OV, max_lines=1),
        )

    header = ft.DataTable(
        columns=[ft.DataColumn(ft.Container(ft.TextButton(text=c, on_click=lambda e,i=i:apply_sort(i),
                                                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
                                             width=COL_W[c])) for i, c in enumerate(COLUMNS)],
        rows=[], heading_row_height=HEAD_H, data_row_max_height=0, column_spacing=6,
    )

    body = ft.DataTable(
        columns=[ft.DataColumn(ft.Container(ft.Text(c, size=UI_SIZE), width=COL_W[c])) for c in COLUMNS],
        rows=[], heading_row_height=0, data_row_max_height=ROW_H, column_spacing=6,
    )

    # --- Paginação ---
    lbl_page = ft.Text("", size=UI_SIZE)
    dd_page = ft.Dropdown(width=90, value="100",
                          options=[ft.dropdown.Option(str(x)) for x in (50,100,200)],
                          text_size=UI_SIZE,
                          on_change=lambda e: change_page_size())

    def change_page_size():
        nonlocal page_size, current_page
        try: page_size=int(dd_page.value)
        except: page_size=100
        current_page=1
        refresh_table()

    def refresh_table():
        body.rows.clear()
        total=len(filtered)
        if total==0:
            lbl_page.value="0/0"
            body.update(); lbl_page.update()
            return
        last=max(1,(total+page_size-1)//page_size)
        cp=min(max(1,current_page), last)
        s=(cp-1)*page_size; e=min(s+page_size,total)

        for r in filtered[s:e]:
            icon=""
            st=(r.get("Status") or "").lower()
            if ("cancelada" in st and "135" in st): icon="X"
            elif ("confirmação da operação" in st and "135" in st): icon="XML"
            vals=[icon if col=="Ícone" else r.get(col,"") for col in COLUMNS]
            def _on_select(chave=r.get("Chave")):
                return lambda *_: select_row(chave)
            body.rows.append(
                ft.DataRow(
                    cells=[ft.DataCell(cell(vals[i], COLUMNS[i])) for i in range(len(COLUMNS))],
                    on_select_changed=lambda e, f=_on_select(): f()
                )
            )
        lbl_page.value=f"{cp}/{last}  (itens {s+1}-{e} de {total})"
        body.update(); lbl_page.update()

    def page_prev(e=None):
        nonlocal current_page
        if current_page>1:
            current_page-=1; refresh_table()
    def page_next(e=None):
        nonlocal current_page
        last=max(1,(len(filtered)+page_size-1)//page_size)
        if current_page<last:
            current_page+=1; refresh_table()

    # --- Carregar/filtrar ---
    def load_all():
        nonlocal all_rows
        if not db.table_exists():
            dlog(f"[LOAD] Tabela 'notas_detalhadas' NÃO existe em {db.path}")
            all_rows = []
            set_status("Tabela 'notas_detalhadas' não encontrada neste banco.", C.ORANGE)
            return
        rows = db.fetch_all()
        out=[]
        for rec in rows:
            st = (rec.get("status") or "").strip()
            st_low = st.lower()
            status = "Cancelada" if (("cancelamento" in st_low or "cancelada" in st_low) and "135" in st_low) else st
            out.append({
                "Ícone":"",
                "IE Tomador": rec.get("ie_tomador") or "",
                "Nome": rec.get("nome_emitente") or rec.get("nome") or "",
                "CNPJ/CPF": rec.get("cnpj_emitente") or rec.get("cnpj_cpf") or "",
                "Num": rec.get("numero") or "",
                "DtEmi": parse_dt_emi(rec.get("data_emissao") or ""),
                "Tipo": rec.get("tipo") or "NFe",
                "Valor": rec.get("valor") or "",
                "CFOP": rec.get("cfop") or "",
                "Vencimento": rec.get("vencimento") or "",
                "Status": status,
                "UF": rec.get("uf") or "",
                "Chave": rec.get("chave") or "",
                "Natureza": rec.get("natureza") or "",
                "_RAW": rec
            })
        all_rows = out
        dlog(f"[LOAD] {len(all_rows)} linhas carregadas de {db.path}")

    def apply_filters(e=None):
        nonlocal filtered, current_page
        def validate_date(s: str) -> Optional[date]:
            try: return datetime.strptime(s, "%d/%m/%Y").date()
            except: return None
        def ok_date(s, d1, d2):
            if not (d1 or d2): return True
            try:
                d = datetime.strptime(s, "%d/%m/%Y").date()
                if d1 and d<d1: return False
                if d2 and d>d2: return False
                return True
            except: return False

        n  = only_digits(tf_num.value)
        ch = only_digits(tf_chave.value)
        nm = (tf_nome.value or "").strip().lower()
        d1 = validate_date(dt_ini.value) if dt_ini.value else None
        d2 = validate_date(dt_fim.value) if dt_fim.value else None

        base = all_rows[:]
        if n:  base=[r for r in base if n in only_digits(str(r.get("Num","")))]
        if ch: base=[r for r in base if ch in only_digits(str(r.get("Chave","")))]
        if nm: base=[r for r in base if nm in (r.get("Nome","").lower())]
        filtered=[r for r in base if ok_date(r.get("DtEmi",""), d1, d2)]

        dlog(f"[FILTER] {len(filtered)} linhas após filtro.")
        current_page=1
        if sort_col is not None:
            apply_sort(sort_col)
        else:
            refresh_table()
        set_status(f"{len(filtered)} notas.")

    # --- Painel de edição ---
    fe_chave   = ft.TextField(label="Chave (44)", width=360, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_ie      = ft.TextField(label="IE Tomador", width=180, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_nome    = ft.TextField(label="Nome emitente", width=260, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_cnpj    = ft.TextField(label="CNPJ emitente", width=180, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_num     = ft.TextField(label="Número", width=120, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                              keyboard_type=ft.KeyboardType.NUMBER)
    fe_dt      = ft.TextField(label="Dt Emissão (dd/mm/aaaa)", width=160, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                              keyboard_type=ft.KeyboardType.NUMBER, on_change=lambda e: mask_date(e.control))
    fe_tipo    = ft.TextField(label="Tipo", width=80, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE), value="NFe")
    fe_valor   = ft.TextField(label="Valor (R$)", width=130, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_cfop    = ft.TextField(label="CFOP", width=90, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_venc    = ft.TextField(label="Vencimento (dd/mm/aaaa)", width=170, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE),
                              keyboard_type=ft.KeyboardType.NUMBER, on_change=lambda e: mask_date(e.control))
    fe_uf      = ft.TextField(label="UF", width=70, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_nat     = ft.TextField(label="Natureza", width=260, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_status  = ft.TextField(label="Status", width=300, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_cnpj_dest = ft.TextField(label="CNPJ destinatário", width=180, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))
    fe_nome_dest = ft.TextField(label="Nome destinatário", width=260, height=36, text_size=UI_SIZE, label_style=ft.TextStyle(size=UI_SIZE))

    def clear_form():
        nonlocal selection_chave
        for tf in (fe_chave, fe_ie, fe_nome, fe_cnpj, fe_num, fe_dt, fe_tipo, fe_valor,
                   fe_cfop, fe_venc, fe_uf, fe_nat, fe_status, fe_cnpj_dest, fe_nome_dest):
            tf.value=""
            tf.update()
        selection_chave=None
        set_status("Pronto para inserir um novo registro.")

    def fill_form(rec: Dict[str, Any]):
        fe_chave.value = rec.get("chave","")
        fe_ie.value    = rec.get("ie_tomador","")
        fe_nome.value  = rec.get("nome_emitente","") or rec.get("nome","")
        fe_cnpj.value  = rec.get("cnpj_emitente","") or rec.get("cnpj_cpf","")
        fe_num.value   = rec.get("numero","")
        fe_dt.value    = parse_dt_emi(rec.get("data_emissao",""))
        fe_tipo.value  = rec.get("tipo","") or "NFe"
        fe_valor.value = rec.get("valor","")
        fe_cfop.value  = rec.get("cfop","")
        fe_venc.value  = rec.get("vencimento","")
        fe_uf.value    = rec.get("uf","")
        fe_nat.value   = rec.get("natureza","")
        fe_status.value= rec.get("status","")
        fe_cnpj_dest.value = rec.get("cnpj_destinatario","")
        fe_nome_dest.value = rec.get("nome_destinatario","")
        for tf in (fe_chave, fe_ie, fe_nome, fe_cnpj, fe_num, fe_dt, fe_tipo, fe_valor,
                   fe_cfop, fe_venc, fe_uf, fe_nat, fe_status, fe_cnpj_dest, fe_nome_dest):
            tf.update()

    def select_row(chave: str):
        nonlocal selection_chave
        selection_chave = chave
        raw = db.get_by_chave(chave)
        if not raw:
            set_status("Registro não encontrado!", C.RED); return
        fill_form(raw)
        set_status(f"Editando chave {chave[:6]}…")

    def form_to_record() -> Dict[str, Any]:
        ch = only_digits(fe_chave.value)
        if len(ch)!=44:
            raise ValueError("Chave deve ter 44 dígitos.")
        dt = fe_dt.value.strip()
        if dt and not validate_ddmmyyyy(dt):
            raise ValueError("Data de emissão inválida (use dd/mm/aaaa).")
        vc = fe_venc.value.strip()
        if vc and not validate_ddmmyyyy(vc):
            raise ValueError("Vencimento inválido (use dd/mm/aaaa).")
        return {
            "chave": ch,
            "ie_tomador": (fe_ie.value or "").strip(),
            "nome_emitente": (fe_nome.value or "").strip(),
            "cnpj_emitente": only_digits(fe_cnpj.value),
            "numero": (fe_num.value or "").strip(),
            "data_emissao": dt,
            "tipo": (fe_tipo.value or "NFe").strip(),
            "valor": (fe_valor.value or "").strip(),
            "cfop": (fe_cfop.value or "").strip(),
            "vencimento": vc,
            "uf": (fe_uf.value or "").strip(),
            "natureza": (fe_nat.value or "").strip(),
            "status": (fe_status.value or "").strip(),
            "cnpj_destinatario": only_digits(fe_cnpj_dest.value),
            "nome_destinatario": (fe_nome_dest.value or "").strip(),
            # compat:
            "cnpj_cpf": only_digits(fe_cnpj.value) or only_digits(fe_cnpj_dest.value),
            "nome": (fe_nome.value or fe_nome_dest.value or "").strip()
        }

    def save_form():
        try:
            rec = form_to_record()
            db.upsert(rec)
            set_status("Registro salvo.")
            reload_all(select_chave=rec["chave"])
        except Exception as ex:
            set_status(f"Erro ao salvar: {ex}", C.RED)

    def delete_current():
        ch = only_digits(fe_chave.value)
        if len(ch)!=44:
            set_status("Informe uma chave válida para excluir.", C.RED); return
        def really(_):
            try:
                db.delete(ch)
                dlg.open=False; page.update()
                clear_form()
                reload_all()
                set_status("Registro excluído.", C.RED)
            except Exception as ex:
                set_status(f"Erro ao excluir: {ex}", C.RED)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirmar exclusão"),
            content=ft.Text(f"Excluir a chave {ch}?"),
            actions=[ft.TextButton("Cancelar", on_click=lambda e:(setattr(dlg,'open',False), page.update())),
                     ft.ElevatedButton("Excluir", on_click=really)],
        )
        page.dialog=dlg; dlg.open=True; page.update()

    # --- Layout: filtros + botões DB ---
    def mask_date(tf: ft.TextField):
        raw = only_digits(tf.value)[:8]
        tf.value = raw if len(raw)<3 else (f"{raw[:2]}/{raw[2:]}" if len(raw)<5 else f"{raw[:2]}/{raw[2:4]}/{raw[4:]}")
        tf.update()

    filtros = ft.Row([
        tf_num, tf_chave, tf_nome, dt_ini, dt_fim,
        ft.ElevatedButton("Aplicar filtros", height=32,
                          on_click=lambda e: apply_filters(),
                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
        ft.ElevatedButton("Recarregar", height=32,
                          on_click=lambda e: reload_all(),
                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
    ], spacing=12, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    db_bar = ft.Row([
        current_db_txt,
        ft.ElevatedButton("Detectar banco automaticamente", on_click=auto_detect_db, height=28,
                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
        ft.ElevatedButton("Trocar banco…", on_click=choose_db, height=28,
                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
        ft.ElevatedButton("Criar tabela (se faltar)", on_click=create_table_now, height=28,
                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
    ], spacing=10, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    # --- Grid com header fixo / corpo rolando ---
    header = ft.DataTable(
        columns=[ft.DataColumn(ft.Container(ft.TextButton(text=c, on_click=lambda e,i=i:apply_sort(i),
                                                          style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
                                             width=COL_W[c])) for i, c in enumerate(COLUMNS)],
        rows=[], heading_row_height=HEAD_H, data_row_max_height=0, column_spacing=6,
    )
    body = ft.DataTable(
        columns=[ft.DataColumn(ft.Container(ft.Text(c, size=UI_SIZE), width=COL_W[c])) for c in COLUMNS],
        rows=[], heading_row_height=0, data_row_max_height=ROW_H, column_spacing=6,
    )
    try: OV = ft.TextOverflow.ELLIPSIS
    except Exception: OV = None
    def cell(val, col):
        align = ft.alignment.center_left
        if col in RIGHT_ALIGN: align=ft.alignment.center_right
        elif col in CENTER_ALIGN: align=ft.alignment.center
        return ft.Container(width=COL_W[col], alignment=align,
                            padding=ft.padding.symmetric(vertical=4),
                            content=ft.Text(str(val or ""), size=UI_SIZE, no_wrap=True, overflow=OV, max_lines=1))

    def select_row(chave: str):
        nonlocal selection_chave
        selection_chave = chave
        raw = db.get_by_chave(chave)
        if not raw:
            set_status("Registro não encontrado!", C.RED); return
        fill_form(raw)
        set_status(f"Editando chave {chave[:6]}…")

    def refresh_table():
        body.rows.clear()
        total=len(filtered)
        if total==0:
            lbl_page.value="0/0"
            body.update(); lbl_page.update()
            return
        last=max(1,(total+page_size-1)//page_size)
        cp=min(max(1,current_page), last)
        s=(cp-1)*page_size; e=min(s+page_size,total)
        for r in filtered[s:e]:
            icon=""
            st=(r.get("Status") or "").lower()
            if ("cancelada" in st and "135" in st): icon="X"
            elif ("confirmação da operação" in st and "135" in st): icon="XML"
            vals=[icon if col=="Ícone" else r.get(col,"") for col in COLUMNS]
            def _on_select(chave=r.get("Chave")):
                return lambda *_: select_row(chave)
            body.rows.append(
                ft.DataRow(
                    cells=[ft.DataCell(cell(vals[i], COLUMNS[i])) for i in range(len(COLUMNS))],
                    on_select_changed=lambda e, f=_on_select(): f()
                )
            )
        lbl_page.value=f"{cp}/{last}  (itens {s+1}-{e} de {total})"
        body.update(); lbl_page.update()

    lbl_page = ft.Text("", size=UI_SIZE)
    dd_page = ft.Dropdown(width=90, value="100",
                          options=[ft.dropdown.Option(str(x)) for x in (50,100,200)],
                          text_size=UI_SIZE,
                          on_change=lambda e: change_page_size())

    def change_page_size():
        nonlocal page_size, current_page
        try: page_size=int(dd_page.value)
        except: page_size=100
        current_page=1
        refresh_table()

    def page_prev(e=None):
        nonlocal current_page
        if current_page>1:
            current_page-=1; refresh_table()
    def page_next(e=None):
        nonlocal current_page
        last=max(1,(len(filtered)+page_size-1)//page_size)
        if current_page<last:
            current_page+=1; refresh_table()

    header_wrap = ft.Container(header, width=TOTAL_W, padding=ft.padding.only(right=SCROLLBAR))
    body_scroll = ft.Column([ft.Container(body, width=TOTAL_W)], expand=True, spacing=0, scroll=SM_ALWAYS)
    grid_block  = ft.Row([ft.Column([header_wrap, body_scroll], spacing=0, expand=True)], expand=True, scroll=SM_AUTO)

    # --- Painel de edição (mesmo de antes) ---
    fe_tipo    = fe_tipo  # já criados acima
    edit_panel = ft.Column([
        ft.Text("Edição", size=UI_SIZE, weight=ft.FontWeight.BOLD),
        fe_chave, ft.Row([fe_ie, fe_num, fe_dt], spacing=8),
        ft.Row([fe_nome, fe_cnpj], spacing=8),
        ft.Row([fe_tipo, fe_valor, fe_cfop, fe_uf], spacing=8),
        ft.Row([fe_venc, fe_nat], spacing=8),
        fe_status,
        ft.Row([fe_cnpj_dest, fe_nome_dest], spacing=8),
        ft.Row([
            ft.ElevatedButton("Novo", on_click=lambda e: clear_form(), height=32, style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
            ft.ElevatedButton("Salvar", on_click=lambda e: save_form(), height=32, style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
            ft.ElevatedButton("Excluir", on_click=lambda e: delete_current(), height=32, style=ft.ButtonStyle(text_style=ft.TextStyle(size=UI_SIZE))),
        ], spacing=8)
    ], scroll=SM_AUTO, spacing=8, expand=False, width=420)

    # --- Layout final ---
    top_bar = ft.Column([db_bar, filtros], spacing=8)
    pagination = ft.Row([
        ft.IconButton(icon=ICON("KEYBOARD_ARROW_LEFT","chevron_left"), on_click=page_prev, tooltip="Anterior"),
        lbl_page,
        ft.IconButton(icon=ICON("KEYBOARD_ARROW_RIGHT","chevron_right"), on_click=page_next, tooltip="Próxima"),
        ft.Container(width=12),
        ft.Text("Itens:", size=UI_SIZE), dd_page
    ], spacing=6)

    content = ft.Row([grid_block, ft.VerticalDivider(), edit_panel],
                     expand=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)

    log_lv_title = ft.Text("Logs", size=UI_SIZE, weight=ft.FontWeight.BOLD)

    root = ft.Column([
        top_bar, content, pagination, ft.Divider(), status, log_lv_title, log_lv
    ], expand=True, spacing=8)

    page.add(root)

    # --- Carregamento inicial ---
    def reload_all(select_chave: Optional[str]=None):
        nonlocal selection_chave
        selection_chave = None
        load_all(); apply_filters()
        if select_chave:
            select_row(select_chave)

    reload_all()
    set_status("Pronto.")

if __name__ == "__main__":
    ft.app(target=main)
