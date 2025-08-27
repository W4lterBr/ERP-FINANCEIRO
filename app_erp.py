import os
import sys
import csv
import sqlite3
import hashlib
from datetime import date
from pathlib import Path

from PyQt5.QtCore import Qt, QDate, QRegExp, QPoint, QSizeF, pyqtSignal, QProcess
from PyQt5.QtGui import QRegExpValidator, QTextDocument
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QComboBox, QLineEdit, QPushButton, QHBoxLayout,
    QVBoxLayout, QFormLayout, QGridLayout, QMessageBox, QMainWindow, QAction, QDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QSpinBox, QDateEdit, QRadioButton,
    QFileDialog, QStyledItemDelegate, QAbstractScrollArea, QAbstractItemView, QMenu,
    QListWidget, QListWidgetItem, QCheckBox, QTextEdit
)
from PyQt5.QtPrintSupport import QPrinter
from hmac import compare_digest as secure_eq

DB_FILE = "erp_financeiro.db"
APP_TITLE = "ERP Financeiro"

# =============================================================================
# Utilidades UI / auto-ajuste
# =============================================================================
def enable_autosize(widget, w_ratio=0.9, h_ratio=0.85, min_w=1100, min_h=680):
    try:
        widget.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        widget.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
    except Exception:
        pass
    if isinstance(widget, QDialog):
        try:
            widget.setSizeGripEnabled(True)
        except Exception:
            pass
    scr = QApplication.primaryScreen()
    if scr:
        g = scr.availableGeometry()
        w = max(min_w, int(g.width() * float(w_ratio)))
        h = max(min_h, int(g.height() * float(h_ratio)))
        widget.resize(w, h)
    else:
        widget.resize(min_w, min_h)

def stretch_table(table: QTableWidget):
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.Stretch)
    table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
    table.setMinimumHeight(320)

def zebra_table(table: QTableWidget, gray="#EEEEEE"):
    table.setAlternatingRowColors(True)
    table.setStyleSheet(f"QTableWidget {{ alternate-background-color: {gray}; }}")

def std_icon(widget, sp):
    return widget.style().standardIcon(sp)

def msg_info(text, parent=None):
    QMessageBox.information(parent, APP_TITLE, text)

def msg_err(text, parent=None):
    QMessageBox.critical(parent, APP_TITLE, text)

def msg_yesno(text, parent=None):
    return QMessageBox.question(parent, APP_TITLE, text, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

def set_br_date(edit: QDateEdit):
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd/MM/yyyy")

def qdate_to_iso(qd: QDate) -> str:
    return f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"

def iso_to_br(iso: str) -> str:
    if not iso:
        return ""
    try:
        y, m, d = iso.split("-")
        return f"{int(d):02d}/{int(m):02d}/{int(y):04d}"
    except Exception:
        return iso

# =============================================================================
# Helpers BR + moeda
# =============================================================================
UF_SET = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA",
    "PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}
def only_digits(s: str) -> str: return "".join(ch for ch in (s or "") if ch.isdigit())

def format_cnpj(d: str) -> str:
    d = only_digits(d);  return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}" if len(d)==14 else d
def format_cpf(d: str) -> str:
    d = only_digits(d);  return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}" if len(d)==11 else d
def validate_cnpj(cnpj: str) -> bool:
    d = only_digits(cnpj)
    if len(d) != 14 or d == d[0]*14: return False
    def dv(nums, w): t=sum(int(n)*ww for n,ww in zip(nums,w)); r=t%11; return '0' if r<2 else str(11-r)
    w1=[5,4,3,2,9,8,7,6,5,4,3,2]; w2=[6]+w1
    return d[-2:]==dv(d[:12],w1)+dv(d[:12]+dv(d[:12],w1),w2)
def validate_cpf(cpf: str) -> bool:
    d = only_digits(cpf)
    if len(d)!=11 or d==d[0]*11: return False
    def dv(nums,m): s=sum(int(nums[i])*(m-i) for i in range(len(nums))); r=(s*10)%11; return '0' if r==10 else str(r)
    return d[-2:]==dv(d[:9],10)+dv(d[:9]+dv(d[:9],10),11)
def validate_cep(cep: str) -> bool: return len(only_digits(cep))==8
def validate_uf(uf: str) -> bool: return (uf or "").upper() in UF_SET

def fmt_brl(v: float) -> str:
    s = f"{float(v):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")

def parse_brl(text: str) -> float:
    if text is None: return 0.0
    s = str(text).strip()
    if not s: return 0.0
    s = s.replace("R$", "").strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

class BRLCurrencyLineEdit(QLineEdit):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setAlignment(Qt.AlignRight)
    def focusOutEvent(self, e):
        self.setText(fmt_brl(parse_brl(self.text())))
        super().focusOutEvent(e)
    def value(self) -> float:
        return parse_brl(self.text())
    def setValue(self, v: float):
        self.setText(fmt_brl(v))

# =============================================================================
# Delegates (robustos a tipos)
# =============================================================================

class MaskDelegate(QStyledItemDelegate):
    """
    Delegate genérico para QLineEdit com máscara e/ou regex.
    - Converte qualquer dado para str ao entrar no editor (evita TypeError).
    - Opcionalmente aplica uppercase na gravação.
    """
    def __init__(self, mask: str = None, regex: str = None, uppercase: bool = False, parent=None):
        super().__init__(parent)
        self.mask = mask
        self.regex = regex
        self.uppercase = uppercase

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        if self.mask:
            ed.setInputMask(self.mask)
        if self.regex:
            ed.setValidator(QRegExpValidator(QRegExp(self.regex), ed))
        return ed

    def setEditorData(self, editor, index):
        val = index.data()
        editor.setText("" if val is None else str(val))

    def setModelData(self, editor, model, index):
        text = editor.text() or ""
        if self.uppercase:
            text = text.upper()
        model.setData(index, text)


class DocNumberDelegate(QStyledItemDelegate):
    """
    CNPJ/CPF com formatação automática enquanto digita.
    - Aceita digitar/colar apenas dígitos (demais caracteres são ignorados).
    - Formata progressivamente: CPF quando <= 11 dígitos, CNPJ quando > 11 (até 14).
    - Ao salvar no modelo, mantém o texto já formatado (o seu save já usa only_digits).
    """

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        # Formata em tempo real sempre que o usuário editar (não dispara em setText por código).
        ed.textEdited.connect(lambda _=None, e=ed: self._live_format(e))
        return ed

    def setEditorData(self, editor, index):
        val = index.data()
        s = "" if val is None else str(val)
        # normaliza e aplica formatação ao abrir o editor
        editor.setText(self._format_progressive(only_digits(s)))
        editor.setCursorPosition(len(editor.text()))

    def setModelData(self, editor, model, index):
        # já gravamos formatado (seu save usa only_digits antes de ir ao banco)
        model.setData(index, editor.text())

    # ---------------- helpers ----------------
    def _live_format(self, ed: QLineEdit):
        """Formata enquanto digita e limita a 14 dígitos."""
        d = only_digits(ed.text())[:14]
        txt = self._format_progressive(d)

        # evita loops de sinal; textEdited não dispara com setText, mas textChanged sim.
        blocked = ed.blockSignals(True)
        ed.setText(txt)
        ed.blockSignals(blocked)
        ed.setCursorPosition(len(txt))

    def _format_progressive(self, d: str) -> str:
        """Escolhe CPF (<=11) ou CNPJ (>11) e formata parcialmente."""
        if len(d) <= 11:
            return self._fmt_cpf_live(d)
        return self._fmt_cnpj_live(d[:14])

    def _fmt_cpf_live(self, d: str) -> str:
        # padrão CPF: 000.000.000-00 (parcial)
        n = len(d)
        if n <= 3:
            return d
        if n <= 6:
            return f"{d[:3]}.{d[3:]}"
        if n <= 9:
            return f"{d[:3]}.{d[3:6]}.{d[6:]}"
        # 10–11
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"

    def _fmt_cnpj_live(self, d: str) -> str:
        # padrão CNPJ: 00.000.000/0000-00 (parcial)
        n = len(d)
        if n <= 2:
            return d
        if n <= 5:
            return f"{d[:2]}.{d[2:]}"
        if n <= 8:
            return f"{d[:2]}.{d[2:5]}.{d[5:]}"
        if n <= 12:
            return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:]}"
        # 13–14
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"

class KindComboDelegate(QStyledItemDelegate):
    """
    Delegate para o campo Tipo na tela de Entidades.
    Opções: FORNECEDOR, CLIENTE, AMBOS (incluído para compatibilidade com o schema).
    """
    OPTIONS = ["FORNECEDOR", "CLIENTE", "AMBOS"]

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(self.OPTIONS)
        cb.setEditable(False)
        return cb

    def setEditorData(self, editor, index):
        val = index.data()
        up = ("" if val is None else str(val)).upper()
        if up not in self.OPTIONS:
            up = "FORNECEDOR"
        i = editor.findText(up, Qt.MatchFixedString)
        editor.setCurrentIndex(0 if i < 0 else i)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())


class AccountTypeDelegate(QStyledItemDelegate):
    """
    Delegate para o campo 'Tipo' na tela de Bancos.
    Opções fixas: Corrente, Poupança. Não permite edição livre.
    Também normaliza valores antigos (ex.: 'CAIXA', 'CC', 'CP').
    """
    OPTIONS = ["Corrente", "Poupança"]

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(self.OPTIONS)
        cb.setEditable(False)
        return cb

    def setEditorData(self, editor, index):
        val = index.data()
        txt = "" if val is None else str(val)
        up = txt.upper()
        if up in ("CAIXA", "CORRENTE", "CONTA CORRENTE", "CC", "CTE"):
            txt = "Corrente"
        elif up in ("POUPANCA", "POUPANÇA", "CP"):
            txt = "Poupança"
        i = editor.findText(txt, Qt.MatchFixedString)
        editor.setCurrentIndex(0 if i < 0 else i)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())

# =============================================================================
# DB schema / seed
# =============================================================================
SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cnpj TEXT UNIQUE, razao_social TEXT NOT NULL,
  contato1 TEXT, contato2 TEXT, rua TEXT, bairro TEXT, numero TEXT, cep TEXT,
  uf TEXT CHECK (uf IS NULL OR length(uf)=2), cidade TEXT, email TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
  password_salt BLOB NOT NULL, password_hash BLOB NOT NULL, iterations INTEGER NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')),
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS user_company_access (
  user_id INTEGER NOT NULL, company_id INTEGER NOT NULL,
  PRIMARY KEY (user_id, company_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS permission_types (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT
);

CREATE TABLE IF NOT EXISTS user_permissions (
  user_id INTEGER NOT NULL, perm_id INTEGER NOT NULL, allowed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, perm_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (perm_id) REFERENCES permission_types(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bank_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  bank_name TEXT NOT NULL, account_name TEXT, account_type TEXT,
  agency TEXT, account_number TEXT,
  initial_balance REAL NOT NULL DEFAULT 0.0, current_balance REAL NOT NULL DEFAULT 0.0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('FORNECEDOR','CLIENTE','AMBOS')),
  cnpj_cpf TEXT, razao_social TEXT NOT NULL, contato1 TEXT, contato2 TEXT,
  rua TEXT, bairro TEXT, numero TEXT, cep TEXT, uf TEXT, cidade TEXT, email TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name TEXT NOT NULL, tipo TEXT NOT NULL CHECK (tipo IN ('PAGAR','RECEBER')),
  UNIQUE(company_id, name, tipo)
);

CREATE TABLE IF NOT EXISTS subcategories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  UNIQUE(category_id, name)
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN ('PAGAR','RECEBER')),
  entity_id INTEGER REFERENCES entities(id),
  category_id INTEGER REFERENCES categories(id),
  subcategory_id INTEGER REFERENCES subcategories(id),
  descricao TEXT, data_lanc TEXT NOT NULL, data_venc TEXT NOT NULL,
  forma_pagto TEXT, parcelas_qtd INTEGER NOT NULL DEFAULT 1,
  valor REAL NOT NULL CHECK (valor >= 0),
  status TEXT NOT NULL DEFAULT 'EM_ABERTO' CHECK (status IN ('EM_ABERTO','LIQUIDADO','CANCELADO')),
  banco_id_padrao INTEGER REFERENCES bank_accounts(id),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT
);

CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  company_id INTEGER NOT NULL, payment_date TEXT NOT NULL,
  bank_id INTEGER NOT NULL REFERENCES bank_accounts(id),
  amount REAL NOT NULL CHECK (amount >= 0),
  interest REAL NOT NULL DEFAULT 0, discount REAL NOT NULL DEFAULT 0,
  doc_ref TEXT, created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS periods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  year INTEGER NOT NULL CHECK (year BETWEEN 1900 AND 3000),
  status TEXT NOT NULL CHECK (status IN ('OPEN','CLOSED')) DEFAULT 'OPEN',
  locked_at TEXT, locked_by INTEGER REFERENCES users(id),
  UNIQUE(company_id, month, year)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL DEFAULT (datetime('now')),
  user_id INTEGER, action TEXT NOT NULL, table_name TEXT NOT NULL, record_id INTEGER, details TEXT
);

CREATE INDEX IF NOT EXISTS idx_trans_company_venc ON transactions(company_id, data_venc);
CREATE INDEX IF NOT EXISTS idx_trans_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_payments_tx ON payments(transaction_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_entities_company ON entities(company_id);
CREATE INDEX IF NOT EXISTS idx_bank_company ON bank_accounts(company_id);

CREATE VIEW IF NOT EXISTS vw_transactions_lista AS
SELECT t.id, t.company_id, t.tipo, t.entity_id, t.category_id, t.subcategory_id,
       t.descricao, t.data_lanc, t.data_venc, t.forma_pagto, t.parcelas_qtd, t.valor,
       CASE WHEN t.status='LIQUIDADO' THEN 'LIQUIDADO'
            WHEN date(t.data_venc) < date('now') THEN 'ATRASADO'
            ELSE 'EM_ABERTO' END AS status_calc,
       IFNULL((SELECT ROUND(SUM(p.amount + p.interest - p.discount), 2)
               FROM payments p WHERE p.transaction_id=t.id), 0) AS total_pago
FROM transactions t;

CREATE VIEW IF NOT EXISTS vw_fluxo_caixa AS
SELECT p.company_id, p.payment_date AS data, b.bank_name, b.account_name,
       CASE WHEN t.tipo='RECEBER'
            THEN (p.amount + p.interest - p.discount)
            ELSE -(p.amount + p.interest - p.discount) END AS valor_efeito,
       t.id AS transaction_id, p.id AS payment_id
FROM payments p
JOIN transactions t ON t.id=p.transaction_id
JOIN bank_accounts b ON b.id=p.bank_id;

CREATE VIEW IF NOT EXISTS vw_dre_competencia AS
SELECT company_id, strftime('%Y', data_lanc) AS ano, strftime('%m', data_lanc) AS mes,
       tipo, category_id, ROUND(SUM(valor),2) AS total
FROM transactions
WHERE status <> 'CANCELADO'
GROUP BY company_id, ano, mes, tipo, category_id;

CREATE VIEW IF NOT EXISTS vw_dre_caixa AS
SELECT p.company_id, strftime('%Y', p.payment_date) AS ano, strftime('%m', p.payment_date) AS mes,
       t.tipo, t.category_id,
       ROUND(SUM(CASE WHEN t.tipo='RECEBER'
                 THEN (p.amount + p.interest - p.discount)
                 ELSE -(p.amount + p.interest - p.discount) END),2) AS total
FROM payments p
JOIN transactions t ON t.id=p.transaction_id
GROUP BY p.company_id, ano, mes, t.tipo, t.category_id;
"""

SEED_SQL = r"""
INSERT OR IGNORE INTO permission_types(code, name, description) VALUES
  ('CONTAS','Contas a Pagar/Receber','Acesso a lançamentos e baixas'),
  ('BANCOS','Cadastro de Bancos','Manter contas bancárias'),
  ('FORNECEDOR_CLIENTE','Fornecedor/Cliente','Cadastro de entidades'),
  ('NFE','Emissão NFS-e','Acesso a NFS-e'),
  ('DRE','DRE','Relatório de resultados');

INSERT OR IGNORE INTO companies (id, cnpj, razao_social, cidade, uf)
VALUES (1,'00000000000000','EMPRESA DEMONSTRAÇÃO LTDA','Campo Grande','MS');

INSERT OR IGNORE INTO bank_accounts(company_id, bank_name, account_name, account_type, initial_balance, current_balance)
VALUES (1,'CAIXA','Caixa','CAIXA',0,0);

INSERT OR IGNORE INTO categories(company_id, name, tipo) VALUES
 (1,'PRESTACAO DE SERVICOS','RECEBER'),
 (1,'RETENCOES DE IMPOSTOS','PAGAR'),
 (1,'DESPESAS OPERACIONAIS','PAGAR'),
 (1,'DESPESAS DE ESCRITORIO','PAGAR'),
 (1,'RECEITAS BANCARIAS','RECEBER');

INSERT OR IGNORE INTO subcategories (category_id, name)
SELECT id,'OUTROS' FROM categories WHERE company_id=1 AND name='DESPESAS OPERACIONAIS' AND tipo='PAGAR';
"""

# =============================================================================
# Conexão / hashing
# =============================================================================
def pbkdf2_hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

def ensure_db():
    path = Path(DB_FILE)
    first = not path.exists()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_SQL)
    if first:
        conn.executescript(SEED_SQL)
        cur = conn.cursor()
        salt = os.urandom(16); iters = 240_000
        pw_hash = pbkdf2_hash("admin123", salt, iters)
        cur.execute("""INSERT INTO users(name, username, password_salt, password_hash, iterations, is_admin, active)
                       VALUES(?,?,?,?,?,1,1)""", ("Administrador","admin",salt,pw_hash,iters))
        admin_id = cur.lastrowid
        cur.execute("INSERT OR IGNORE INTO user_company_access(user_id, company_id) VALUES(?,1)", (admin_id,))
        for (pid,) in conn.execute("SELECT id FROM permission_types"):
            conn.execute("INSERT OR REPLACE INTO user_permissions(user_id,perm_id,allowed) VALUES(?,?,1)",
                         (admin_id, pid))
        conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('schema_version','1')")
        conn.commit()

    # <<< ADICIONE ESTA LINHA >>>
    seed_default_categories(conn)

    conn.row_factory = sqlite3.Row
    return conn
def seed_default_categories(conn: sqlite3.Connection) -> None:
    """
    Garante categorias/subcategorias padrão:
      - PAGAR: DESPESAS COM IMPOSTOS -> COFINS, CSLL, IRPJ, PIS
      - RECEBER: PRESTACAO DE SERVICOS -> SERVIÇO PRESTADO
    Executa de forma idempotente (INSERT OR IGNORE).
    """
    cur = conn.cursor()
    companies = cur.execute("SELECT id FROM companies").fetchall()
    for (cid,) in companies:
        # --- PAGAR / DESPESAS COM IMPOSTOS
        cur.execute(
            "INSERT OR IGNORE INTO categories(company_id, name, tipo) VALUES (?, ?, 'PAGAR')",
            (cid, "DESPESAS COM IMPOSTOS"),
        )
        cat_tax = cur.execute(
            "SELECT id FROM categories WHERE company_id=? AND name=? AND tipo='PAGAR'",
            (cid, "DESPESAS COM IMPOSTOS")
        ).fetchone()
        if cat_tax:
            cat_id = cat_tax[0]
            for sub in ["COFINS", "CSLL", "IRPJ", "PIS"]:
                cur.execute(
                    "INSERT OR IGNORE INTO subcategories(category_id, name) VALUES (?, ?)",
                    (cat_id, sub)
                )

        # --- RECEBER / PRESTACAO DE SERVICOS
        cur.execute(
            "INSERT OR IGNORE INTO categories(company_id, name, tipo) VALUES (?, ?, 'RECEBER')",
            (cid, "PRESTACAO DE SERVICOS"),
        )
        cat_rec = cur.execute(
            "SELECT id FROM categories WHERE company_id=? AND name=? AND tipo='RECEBER'",
            (cid, "PRESTACAO DE SERVICOS")
        ).fetchone()
        if cat_rec:
            cur.execute(
                "INSERT OR IGNORE INTO subcategories(category_id, name) VALUES (?, ?)",
                (cat_rec[0], "SERVIÇO PRESTADO")
            )

    conn.commit()
# =============================================================================
# Dados
# =============================================================================
class DB:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    # utilidades básicas
    def q(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def e(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.lastrowid

    # ---------------------- LOGIN / ACL ----------------------
    def list_companies(self):
        return self.q(
            "SELECT id, razao_social FROM companies WHERE active=1 ORDER BY razao_social"
        )

    def list_users_for_company(self, company_id):
        sql = """
            SELECT u.id, u.name, u.username
              FROM users u
              JOIN user_company_access a ON a.user_id = u.id
             WHERE a.company_id = ? AND u.active = 1
             ORDER BY u.name
        """
        return self.q(sql, (company_id,))

    def verify_login(self, company_id, username, password):
        rows = self.q(
            "SELECT * FROM users WHERE username=? AND active=1", (username,)
        )
        if not rows:
            return None
        u = rows[0]
        calc = pbkdf2_hash(password, u["password_salt"], u["iterations"])
        if not secure_eq(calc, u["password_hash"]):
            return None
        ok = self.q(
            "SELECT 1 FROM user_company_access WHERE user_id=? AND company_id=?",
            (u["id"], company_id),
        )
        if not ok:
            return None
        return u

    def is_admin(self, user_id):
        r = self.q("SELECT is_admin FROM users WHERE id=?", (user_id,))
        return bool(r and r[0]["is_admin"])

    # ---------------------- COMPANIES ----------------------
    def companies_all(self):
        return self.q("SELECT * FROM companies ORDER BY razao_social")

    def company_save(self, rec, company_id=None):
        if company_id:
            self.e(
                """UPDATE companies
                      SET cnpj=?, razao_social=?, contato1=?, contato2=?, rua=?, bairro=?, numero=?,
                          cep=?, uf=?, cidade=?, email=?, active=?
                    WHERE id=?""",
                (
                    rec["cnpj"],
                    rec["razao_social"],
                    rec["contato1"],
                    rec["contato2"],
                    rec["rua"],
                    rec["bairro"],
                    rec["numero"],
                    rec["cep"],
                    rec["uf"],
                    rec["cidade"],
                    rec["email"],
                    int(rec["active"]),
                    company_id,
                ),
            )
            return company_id

        return self.e(
            """INSERT INTO companies
               (cnpj, razao_social, contato1, contato2, rua, bairro, numero, cep, uf, cidade, email, active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec["cnpj"],
                rec["razao_social"],
                rec["contato1"],
                rec["contato2"],
                rec["rua"],
                rec["bairro"],
                rec["numero"],
                rec["cep"],
                rec["uf"],
                rec["cidade"],
                rec["email"],
                int(rec["active"]),
            ),
        )

    def company_delete(self, company_id):
        self.e("DELETE FROM companies WHERE id=?", (company_id,))

    # ---------------------- USERS ----------------------
    def users_all(self):
        return self.q("SELECT * FROM users ORDER BY name")

    def user_save(self, rec, user_id=None):
        if user_id:
            self.e(
                """UPDATE users
                      SET name=?, username=?, is_admin=?, active=?
                    WHERE id=?""",
                (
                    rec["name"],
                    rec["username"],
                    int(rec["is_admin"]),
                    int(rec["active"]),
                    user_id,
                ),
            )
            return user_id

        salt = os.urandom(16)
        iters = 240_000
        pw_hash = pbkdf2_hash(rec.get("password", "123456"), salt, iters)
        return self.e(
            """INSERT INTO users
               (name, username, password_salt, password_hash, iterations, is_admin, active)
               VALUES (?,?,?,?,?,?,?)""",
            (
                rec["name"],
                rec["username"],
                salt,
                pw_hash,
                iters,
                int(rec["is_admin"]),
                int(rec["active"]),
            ),
        )

    def user_delete(self, user_id):
        self.e("DELETE FROM users WHERE id=?", (user_id,))

    def user_set_password(self, user_id, password):
        salt = os.urandom(16)
        iters = 240_000
        pw_hash = pbkdf2_hash(password, salt, iters)
        self.e(
            "UPDATE users SET password_salt=?, password_hash=?, iterations=? WHERE id=?",
            (salt, pw_hash, iters, user_id),
        )

    def permissions_all(self):
        return self.q("SELECT * FROM permission_types ORDER BY id")
    def allowed_codes(self, user_id: int, company_id: int | None = None):
        """
        Retorna um set com os códigos de permissão habilitados para o usuário.
        Se for admin, devolve todos os códigos.
        company_id é ignorado aqui (acesso à empresa já foi validado no login).
        """
        if self.is_admin(user_id):
            rows = self.q("SELECT code FROM permission_types")
            return {r["code"] for r in rows}

        sql = """
            SELECT pt.code
            FROM user_permissions up
            JOIN permission_types pt ON pt.id = up.perm_id
            WHERE up.user_id = ? AND up.allowed = 1
        """
        rows = self.q(sql, (user_id,))
        return {r["code"] for r in rows}

    def user_perm_map(self, user_id):
        rows = self.q(
            "SELECT perm_id, allowed FROM user_permissions WHERE user_id=?", (user_id,)
        )
        return {r["perm_id"]: bool(r["allowed"]) for r in rows}

    def set_user_permissions(self, user_id, allowed_perm_ids):
        self.e("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
        for (pid,) in self.q("SELECT id FROM permission_types"):
            allow = 1 if pid in allowed_perm_ids else 0
            self.e(
                "INSERT INTO user_permissions(user_id, perm_id, allowed) VALUES (?,?,?)",
                (user_id, pid, allow),
            )

    def company_access_map(self, user_id):
        rows = self.q(
            "SELECT company_id FROM user_company_access WHERE user_id=?", (user_id,)
        )
        return {r["company_id"] for r in rows}

    def set_company_access(self, user_id, company_ids):
        self.e("DELETE FROM user_company_access WHERE user_id=?", (user_id,))
        for cid in company_ids:
            self.e(
                "INSERT INTO user_company_access(user_id, company_id) VALUES (?,?)",
                (user_id, cid),
            )

    # ---------------------- BANKS ----------------------
    def banks(self, company_id):
        return self.q(
            "SELECT * FROM bank_accounts WHERE company_id=? ORDER BY bank_name, account_name",
            (company_id,),
        )

    def bank_save(self, company_id, rec, bank_id=None):
        if bank_id:
            self.e(
                """UPDATE bank_accounts
                      SET bank_name=?, account_name=?, account_type=?, agency=?, account_number=?,
                          initial_balance=?, current_balance=?, active=?
                    WHERE id=?""",
                (
                    rec["bank_name"],
                    rec["account_name"],
                    rec["account_type"],
                    rec["agency"],
                    rec["account_number"],
                    float(rec["initial_balance"]),
                    float(rec["current_balance"]),
                    int(rec["active"]),
                    bank_id,
                ),
            )
            return bank_id

        return self.e(
            """INSERT INTO bank_accounts
               (company_id, bank_name, account_name, account_type, agency, account_number,
                initial_balance, current_balance, active)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                company_id,
                rec["bank_name"],
                rec["account_name"],
                rec["account_type"],
                rec["agency"],
                rec["account_number"],
                float(rec["initial_balance"]),
                float(rec["current_balance"]),
                int(rec["active"]),
            ),
        )

    def bank_delete(self, bank_id):
        self.e("DELETE FROM bank_accounts WHERE id=?", (bank_id,))

    # ---------------------- ENTITIES ----------------------
    def entities(self, company_id, kind=None):
        if kind:
            return self.q(
                """SELECT * FROM entities
                    WHERE company_id=? AND (kind=? OR kind='AMBOS')
                    ORDER BY razao_social""",
                (company_id, kind),
            )
        return self.q(
            "SELECT * FROM entities WHERE company_id=? ORDER BY razao_social",
            (company_id,),
        )

    def entity_save(self, company_id, rec, entity_id=None):
        if entity_id:
            self.e(
                """UPDATE entities
                      SET kind=?, cnpj_cpf=?, razao_social=?, contato1=?, contato2=?, rua=?, bairro=?, numero=?, cep=?, uf=?, cidade=?, email=?, active=?
                    WHERE id=?""",
                (
                    rec["kind"],
                    rec["cnpj_cpf"],
                    rec["razao_social"],
                    rec["contato1"],
                    rec["contato2"],
                    rec["rua"],
                    rec["bairro"],
                    rec["numero"],
                    rec["cep"],
                    rec["uf"],
                    rec["cidade"],
                    rec["email"],
                    int(rec["active"]),
                    entity_id,
                ),
            )
            return entity_id

        return self.e(
            """INSERT INTO entities
               (company_id, kind, cnpj_cpf, razao_social, contato1, contato2, rua, bairro, numero, cep, uf, cidade, email, active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                company_id,
                rec["kind"],
                rec["cnpj_cpf"],
                rec["razao_social"],
                rec["contato1"],
                rec["contato2"],
                rec["rua"],
                rec["bairro"],
                rec["numero"],
                rec["cep"],
                rec["uf"],
                rec["cidade"],
                rec["email"],
                int(rec["active"]),
            ),
        )

    def entity_delete(self, entity_id):
        self.e("DELETE FROM entities WHERE id=?", (entity_id,))

    # ---------------------- CATEGORIES / SUBCATEGORIES ----------------------
    def categories(self, company_id, tipo=None):
        if tipo:
            return self.q(
                "SELECT * FROM categories WHERE company_id=? AND tipo=? ORDER BY name",
                (company_id, tipo),
            )
        return self.q(
            "SELECT * FROM categories WHERE company_id=? ORDER BY tipo, name",
            (company_id,),
        )

    def category_save(self, company_id, name, tipo, cat_id=None):
        if cat_id:
            self.e(
                "UPDATE categories SET name=?, tipo=? WHERE id=?",
                (name, tipo, cat_id),
            )
            return cat_id
        return self.e(
            "INSERT INTO categories(company_id,name,tipo) VALUES(?,?,?)",
            (company_id, name, tipo),
        )

    def category_delete(self, cat_id):
        self.e("DELETE FROM categories WHERE id=?", (cat_id,))

    def subcategories(self, category_id):
        return self.q(
            "SELECT * FROM subcategories WHERE category_id=? ORDER BY name",
            (category_id,),
        )

    def subcategory_save(self, category_id, name, sub_id=None):
        if sub_id:
            self.e(
                "UPDATE subcategories SET name=?, category_id=? WHERE id=?",
                (name, category_id, sub_id),
            )
            return sub_id
        return self.e(
            "INSERT INTO subcategories(category_id,name) VALUES(?,?)",
            (category_id, name),
        )

    def subcategory_delete(self, sub_id):
        self.e("DELETE FROM subcategories WHERE id=?", (sub_id,))

    # ---------------------- TRANSACTIONS / PAYMENTS ----------------------
    def transactions(self, company_id, tipo=None):
        base = """
            SELECT t.*,
                   IFNULL((SELECT SUM(p.amount + p.interest - p.discount)
                             FROM payments p
                            WHERE p.transaction_id=t.id), 0) AS pago
              FROM transactions t
             WHERE t.company_id=?
        """
        params = [company_id]
        if tipo:
            base += " AND t.tipo=?"
            params.append(tipo)
        base += " ORDER BY date(data_venc)"
        return self.q(base, tuple(params))

    def transaction_save(self, rec, tx_id=None):
        if tx_id:
            sql = """
                UPDATE transactions
                   SET tipo=?, entity_id=?, category_id=?, subcategory_id=?, descricao=?,
                       data_lanc=?, data_venc=?, forma_pagto=?, parcelas_qtd=?, valor=?,
                       banco_id_padrao=?, updated_at=datetime('now')
                 WHERE id=?
            """
            self.e(
                sql,
                (
                    rec["tipo"],
                    rec["entity_id"],
                    rec["category_id"],
                    rec["subcategory_id"],
                    rec["descricao"],
                    rec["data_lanc"],
                    rec["data_venc"],
                    rec["forma_pagto"],
                    int(rec["parcelas_qtd"]),
                    float(rec["valor"]),
                    rec["banco_id_padrao"],
                    tx_id,
                ),
            )
            return tx_id

        sql = """
            INSERT INTO transactions
                (company_id, tipo, entity_id, category_id, subcategory_id, descricao,
                 data_lanc, data_venc, forma_pagto, parcelas_qtd, valor, status,
                 banco_id_padrao, created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'EM_ABERTO',?,?)
        """
        return self.e(
            sql,
            (
                rec["company_id"],
                rec["tipo"],
                rec["entity_id"],
                rec["category_id"],
                rec["subcategory_id"],
                rec["descricao"],
                rec["data_lanc"],
                rec["data_venc"],
                rec["forma_pagto"],
                int(rec["parcelas_qtd"]),
                float(rec["valor"]),
                rec["banco_id_padrao"],
                rec["created_by"],
            ),
        )

    def transaction_delete(self, tx_id):
        self.e("DELETE FROM transactions WHERE id=?", (tx_id,))

    def payments_for(self, tx_id):
        sql = """
            SELECT p.*, b.bank_name||' - '||IFNULL(b.account_name,'') AS banco
              FROM payments p
              JOIN bank_accounts b ON b.id = p.bank_id
             WHERE p.transaction_id=?
             ORDER BY date(p.payment_date)
        """
        return self.q(sql, (tx_id,))

    def payment_add(self, rec):
        sql = """
            INSERT INTO payments
                (transaction_id, company_id, payment_date, bank_id, amount, interest, discount, doc_ref, created_by)
            VALUES (?,?,?,?,?,?,?,?,?)
        """
        return self.e(
            sql,
            (
                rec["transaction_id"],
                rec["company_id"],
                rec["payment_date"],
                rec["bank_id"],
                float(rec["amount"]),
                float(rec["interest"]),
                float(rec["discount"]),
                rec["doc_ref"],
                rec["created_by"],
            ),
        )

    def payment_delete(self, payment_id):
        self.e("DELETE FROM payments WHERE id=?", (payment_id,))

    # ---------------------- DRE / DASHBOARD ----------------------
    def dre(self, company_id, ano, mes=None, regime="COMPETENCIA"):
        src = "vw_dre_competencia" if regime == "COMPETENCIA" else "vw_dre_caixa"
        params = [company_id, str(ano)]
        filt = ""
        if mes:
            filt = " AND mes=? "
            params.append(f"{int(mes):02d}")
        sql = f"""
            SELECT c.name AS categoria, v.tipo, v.total
              FROM {src} v
              JOIN categories c ON c.id = v.category_id
             WHERE v.company_id = ? AND v.ano = ? {filt}
             ORDER BY v.tipo, c.name
        """
        return self.q(sql, tuple(params))

    def resumo_periodo(self, company_id, dt_ini: str, dt_fim_excl: str):
        sql = """
            SELECT t.tipo,
                   ROUND(SUM(t.valor - IFNULL((
                       SELECT SUM(p.amount + p.interest - p.discount)
                         FROM payments p
                        WHERE p.transaction_id=t.id
                   ),0)), 2) AS saldo
              FROM transactions t
             WHERE t.company_id=? 
               AND date(t.data_venc) >= date(?) 
               AND date(t.data_venc) <  date(?)
               AND t.status <> 'CANCELADO'
          GROUP BY t.tipo
        """
        rows = self.q(sql, (company_id, dt_ini, dt_fim_excl))
        res = {"PAGAR": 0.0, "RECEBER": 0.0}
        for r in rows:
            res[r["tipo"]] = max(0.0, float(r["saldo"] or 0.0))
        return res

    def dre_retencoes_por_sub(self, company_id: int, ano: int, mes: int | None, regime: str = "COMPETENCIA"):
        """Retorna dict {'COFINS': v, 'CSLL': v, 'IRPJ': v, 'PIS': v} conforme período/regime."""
        alvo_subs = ("COFINS", "CSLL", "IRPJ", "PIS")
        ret = {k: 0.0 for k in alvo_subs}

        if regime == "COMPETENCIA":
            sql = """
                SELECT s.name AS sub, ROUND(SUM(t.valor), 2) AS total
                  FROM transactions t
                  JOIN categories c   ON c.id = t.category_id
                  JOIN subcategories s ON s.id = t.subcategory_id
                 WHERE t.company_id = ?
                   AND t.tipo = 'PAGAR'
                   AND c.name = 'DESPESAS COM IMPOSTOS'
                   AND t.status <> 'CANCELADO'
                   AND strftime('%Y', t.data_lanc) = ?
                   AND (? IS NULL OR strftime('%m', t.data_lanc) = ?)
                   AND s.name IN ('COFINS','CSLL','IRPJ','PIS')
              GROUP BY s.name
            """
            mes_str = f"{int(mes):02d}" if mes else None
            rows = self.q(sql, (company_id, str(ano), mes_str, mes_str))
        else:  # CAIXA
            sql = """
                SELECT s.name AS sub,
                       ROUND(SUM(p.amount + p.interest - p.discount), 2) AS total
                  FROM payments p
                  JOIN transactions t ON t.id = p.transaction_id
                  JOIN categories   c ON c.id = t.category_id
                  JOIN subcategories s ON s.id = t.subcategory_id
                 WHERE p.company_id = ?
                   AND t.tipo = 'PAGAR'
                   AND c.name = 'DESPESAS COM IMPOSTOS'
                   AND strftime('%Y', p.payment_date) = ?
                   AND (? IS NULL OR strftime('%m', p.payment_date) = ?)
                   AND s.name IN ('COFINS','CSLL','IRPJ','PIS')
              GROUP BY s.name
            """
            mes_str = f"{int(mes):02d}" if mes else None
            rows = self.q(sql, (company_id, str(ano), mes_str, mes_str))

        for r in rows:
            if r["sub"] in ret:
                ret[r["sub"]] = float(r["total"] or 0.0)
        return ret
def table_to_html(table, title: str) -> str:
    head = "<tr>" + "".join(
        f"<th>{table.horizontalHeaderItem(c).text()}</th>"
        for c in range(table.columnCount())
    ) + "</tr>"
    rows = []
    for r in range(table.rowCount()):
        tds = []
        for c in range(table.columnCount()):
            it = table.item(r, c)
            tds.append(f"<td>{'' if it is None else it.text()}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    style = """
    <style>
      body{font-family:Arial,Helvetica,sans-serif;font-size:12px}
      h2{margin:0 0 8px 0}
      table{border-collapse:collapse;width:100%}
      th,td{border:1px solid #888;padding:4px 6px}
      th{background:#eee}
    </style>
    """
    return f"<!doctype html><html><head>{style}</head><body><h2>{title}</h2><table>{head}{''.join(rows)}</table></body></html>"

def export_pdf_from_table(parent, table, title: str):
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
    fn, _ = QFileDialog.getSaveFileName(parent, "Salvar PDF", f"{title}.pdf", "PDF (*.pdf)")
    if not fn:
        return
    if not fn.lower().endswith(".pdf"):
        fn += ".pdf"
    html = table_to_html(table, title)
    doc = QTextDocument()
    doc.setHtml(html)
    pr = QPrinter(QPrinter.HighResolution)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(fn)
    doc.print_(pr)
    QMessageBox.information(parent, "ERP Financeiro", f"PDF gerado em:\n{fn}")

def export_excel_from_table(parent, table, title: str):
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
    try:
        import xlsxwriter
        fn, _ = QFileDialog.getSaveFileName(parent, "Salvar Excel", f"{title}.xlsx", "Excel (*.xlsx)")
        if not fn:
            return
        if not fn.lower().endswith(".xlsx"):
            fn += ".xlsx"
        wb = xlsxwriter.Workbook(fn)
        ws = wb.add_worksheet("Dados")
        # cabeçalho
        for c in range(table.columnCount()):
            ws.write(0, c, table.horizontalHeaderItem(c).text())
        # linhas
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                it = table.item(r, c)
                ws.write(r + 1, c, "" if it is None else it.text())
        wb.close()
        QMessageBox.information(parent, "ERP Financeiro", f"Planilha Excel gerada em:\n{fn}")
    except Exception:
        # fallback CSV
        fn, _ = QFileDialog.getSaveFileName(parent, "Salvar CSV", f"{title}.csv", "CSV (*.csv)")
        if not fn:
            return
        if not fn.lower().endswith(".csv"):
            fn += ".csv"
        with open(fn, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f, delimiter=';')
            wr.writerow([table.horizontalHeaderItem(c).text() for c in range(table.columnCount())])
            for r in range(table.rowCount()):
                wr.writerow([(table.item(r, c).text() if table.item(r, c) else "") for c in range(table.columnCount())])
        QMessageBox.information(parent, "ERP Financeiro", f"CSV gerado em:\n{fn}")
# =============================================================================
# Diálogos base
# =============================================================================
class AdminAuthDialog(QDialog):
    def __init__(self, db: DB, parent=None):
        super().__init__(parent); self.db=db
        self.setWindowTitle("Autenticação de Administrador")
        form = QFormLayout(self)
        self.edUser = QLineEdit(); self.edPass = QLineEdit(); self.edPass.setEchoMode(QLineEdit.Password)
        form.addRow("Usuário:", self.edUser); form.addRow("Senha:", self.edPass)
        bt = QPushButton("Validar"); bt.setIcon(std_icon(self, self.style().SP_DialogApplyButton)); bt.clicked.connect(self.validate)
        form.addRow(bt); self.ok=False; self.user=None
        enable_autosize(self, 0.35, 0.3, 420, 260)
    def validate(self):
        rows = self.db.q("SELECT * FROM users WHERE username=? AND active=1", (self.edUser.text().strip(),))
        if not rows: msg_err("Usuário inválido.", self); return
        u = rows[0]
        calc = hashlib.pbkdf2_hmac("sha256", self.edPass.text().encode("utf-8"), u["password_salt"], u["iterations"])
        if not secure_eq(calc, u["password_hash"]): msg_err("Senha incorreta.", self); return
        if not u["is_admin"]: msg_err("Usuário não é administrador.", self); return
        self.ok=True; self.user=u; self.accept()

# =============================================================================
# Cadastros
# =============================================================================
class CompaniesDialog(QDialog):
    def __init__(self, db: DB, parent=None):
        super().__init__(parent); self.db=db
        self.setWindowTitle("Cadastro de Empresas")

        self.table=QTableWidget(0,14)
        self.table.setHorizontalHeaderLabels([
            "ID","CNPJ","Razão Social","Contato 1","Contato 2",
            "Rua","Bairro","Nº","CEP","UF","Cidade","Email","Ativo","Criado em"
        ])
        stretch_table(self.table); zebra_table(self.table)

        # Oculta ID
        self.table.setColumnHidden(0, True)

        # Máscaras/validações de edição
        # CNPJ com máscara (não vamos validar DV mais)
        self.table.setItemDelegateForColumn(1, MaskDelegate(mask="00.000.000/0000-00;_", parent=self))
        # CEP e UF com validação
        self.table.setItemDelegateForColumn(8, MaskDelegate(mask="00000-000;_", parent=self))
        self.table.setItemDelegateForColumn(9, MaskDelegate(regex=r"[A-Za-z]{0,2}", uppercase=True, parent=self))

        # Botões
        btAdd=QPushButton("Novo"); btSave=QPushButton("Salvar"); btDel=QPushButton("Excluir"); btReload=QPushButton("Recarregar")
        for b,ic in ((btAdd,self.style().SP_FileDialogNewFolder),
                     (btSave,self.style().SP_DialogSaveButton),
                     (btDel,self.style().SP_TrashIcon),
                     (btReload,self.style().SP_BrowserReload)):
            b.setIcon(std_icon(self, ic))
        btAdd.clicked.connect(self.add)
        btSave.clicked.connect(self.save)
        btDel.clicked.connect(self.delete)
        btReload.clicked.connect(self.load)

        lay=QVBoxLayout(self)
        lay.addWidget(self.table)
        hl=QHBoxLayout(); [hl.addWidget(b) for b in (btAdd,btSave,btDel,btReload)]
        lay.addLayout(hl)

        self.load()
        enable_autosize(self, 0.85, 0.75, 1100, 650)

    def load(self):
        rows = self.db.companies_all()
        self.table.setRowCount(0)
        for r in rows:
            row=self.table.rowCount(); self.table.insertRow(row)

            cnpj = format_cnpj(r["cnpj"] or "")
            cep  = r["cep"] or ""
            if cep:
                dcep = only_digits(cep)
                cep  = f"{dcep[:5]}-{dcep[5:]}" if len(dcep)==8 else cep

            data=[r["id"], cnpj, r["razao_social"], r["contato1"], r["contato2"],
                  r["rua"], r["bairro"], r["numero"], cep, (r["uf"] or ""),
                  r["cidade"], r["email"], r["active"], iso_to_br(str(r["created_at"])[:10])]

            for c,val in enumerate(data):
                it=QTableWidgetItem("" if val is None else str(val))
                if c in (0,13):  # ID e "Criado em" não editáveis
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row,c,it)

    def add(self):
        r=self.table.rowCount(); self.table.insertRow(r)
        self.table.setItem(r,0,QTableWidgetItem(""))
        self.table.setItem(r,12,QTableWidgetItem("1"))  # Ativo=1

    def save(self):
        for r in range(self.table.rowCount()):
            id_txt = self.table.item(r,0).text() if self.table.item(r,0) else ""

            # --- CNPJ: aceitar qualquer CNPJ com 14 dígitos (sem checar DV) ---
            cnpj_masked = self.table.item(r,1).text() if self.table.item(r,1) else ""
            cnpj = only_digits(cnpj_masked)
            if cnpj and len(cnpj) != 14:
                msg_err(f"CNPJ deve ter 14 dígitos (linha {r+1}).")
                return

            # CEP e UF continuam com validação básica
            cep = self.table.item(r,8).text() if self.table.item(r,8) else ""
            if cep and not validate_cep(cep):
                msg_err(f"CEP inválido (linha {r+1}).")
                return
            uf = self.table.item(r,9).text().upper() if self.table.item(r,9) else ""
            if uf and not validate_uf(uf):
                msg_err(f"UF inválida (linha {r+1}).")
                return

            rec = dict(
                cnpj=cnpj,
                razao_social=self.table.item(r,2).text() if self.table.item(r,2) else "",
                contato1=self.table.item(r,3).text() if self.table.item(r,3) else "",
                contato2=self.table.item(r,4).text() if self.table.item(r,4) else "",
                rua=self.table.item(r,5).text() if self.table.item(r,5) else "",
                bairro=self.table.item(r,6).text() if self.table.item(r,6) else "",
                numero=self.table.item(r,7).text() if self.table.item(r,7) else "",
                cep=only_digits(cep),
                uf=uf,
                cidade=self.table.item(r,10).text() if self.table.item(r,10) else "",
                email=self.table.item(r,11).text() if self.table.item(r,11) else "",
                active=1 if (self.table.item(r,12) and self.table.item(r,12).text() not in ("0","False","false")) else 0
            )
            if not rec["razao_social"]:
                msg_err("Razão Social é obrigatória.")
                return

            cid = int(id_txt) if id_txt.strip().isdigit() else None
            cid = self.db.company_save(rec, cid)
            self.table.setItem(r,0,QTableWidgetItem(str(cid)))

        msg_info("Empresas salvas.")
        self.load()

    def delete(self):
        r=self.table.currentRow()
        if r < 0:
            return
        id_txt = self.table.item(r,0).text() if self.table.item(r,0) else ""
        if not id_txt.strip().isdigit():
            self.table.removeRow(r); return

        # exige admin
        auth = AdminAuthDialog(self.db, self)
        if not (auth.exec_() and auth.ok):
            return
        if not msg_yesno("Excluir esta empresa?"):
            return
        try:
            self.db.company_delete(int(id_txt))
        except sqlite3.IntegrityError as e:
            msg_err(f"Não foi possível excluir. Existem dados vinculados.\n{e}")
            return
        self.load()

class UsersDialog(QDialog):
    def __init__(self, db: DB, parent=None):
        super().__init__(parent); self.db=db
        self.setWindowTitle("Cadastro de Usuários")
        # tabela usuários
        self.table=QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(["ID","Nome","Usuário","Admin","Ativo","Criado em"])
        stretch_table(self.table); zebra_table(self.table)
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.currentCellChanged.connect(self.load_right_panel)

        # painel direito: acessos e permissões
        self.grpAccess=QGroupBox("Acesso a Empresas"); self.listAccess=QListWidget(); self.listAccess.setSelectionMode(QAbstractItemView.NoSelection)
        la=QVBoxLayout(self.grpAccess); la.addWidget(self.listAccess)
        self.grpPerm=QGroupBox("Permissões"); self.listPerm=QListWidget(); self.listPerm.setSelectionMode(QAbstractItemView.NoSelection)
        lp=QVBoxLayout(self.grpPerm); lp.addWidget(self.listPerm)

        right=QVBoxLayout(); right.addWidget(self.grpAccess); right.addWidget(self.grpPerm)

        # botões
        btAdd=QPushButton("Novo"); btSave=QPushButton("Salvar"); btDel=QPushButton("Excluir"); btReload=QPushButton("Recarregar")
        btPwd=QPushButton("Definir Senha")
        for b,ic in ((btAdd,self.style().SP_FileDialogNewFolder),(btSave,self.style().SP_DialogSaveButton),
                     (btDel,self.style().SP_TrashIcon),(btReload,self.style().SP_BrowserReload),
                     (btPwd,self.style().SP_DialogResetButton)):
            b.setIcon(std_icon(self, ic))
        btAdd.clicked.connect(self.add); btSave.clicked.connect(self.save); btDel.clicked.connect(self.delete)
        btReload.clicked.connect(self.load); btPwd.clicked.connect(self.set_password)

        left=QVBoxLayout(); left.addWidget(self.table); bl=QHBoxLayout(); [bl.addWidget(b) for b in (btAdd,btSave,btDel,btReload,btPwd)]; left.addLayout(bl)

        main=QHBoxLayout(self); main.addLayout(left,2); main.addLayout(right,1)
        self.load(); enable_autosize(self, 0.9, 0.8, 1200, 680)

    def _fill_lists_static(self):
        self.listAccess.clear()
        for c in self.db.list_companies():
            it=QListWidgetItem(c["razao_social"]); it.setData(Qt.UserRole, c["id"]); it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(Qt.Unchecked)
            self.listAccess.addItem(it)
        self.listPerm.clear()
        for p in self.db.permissions_all():
            it=QListWidgetItem(f"{p['name']} ({p['code']})"); it.setData(Qt.UserRole, p["id"]); it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(Qt.Unchecked)
            self.listPerm.addItem(it)

    def load(self):
        self._fill_lists_static()
        rows=self.db.users_all(); self.table.setRowCount(0)
        for r in rows:
            row=self.table.rowCount(); self.table.insertRow(row)
            data=[r["id"], r["name"], r["username"], "1" if r["is_admin"] else "0", "1" if r["active"] else "0", iso_to_br(str(r["created_at"])[:10])]
            for c,val in enumerate(data):
                it=QTableWidgetItem("" if val is None else str(val)); 
                if c in (0,5): it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row,c,it)
        if rows: self.table.selectRow(0); self.load_right_panel(0,0,0,0)

    def load_right_panel(self, *args):
        r=self.table.currentRow()
        if r<0: return
        id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
        if not id_txt.strip().isdigit(): 
            for i in range(self.listAccess.count()): self.listAccess.item(i).setCheckState(Qt.Unchecked)
            for i in range(self.listPerm.count()): self.listPerm.item(i).setCheckState(Qt.Unchecked)
            return
        uid=int(id_txt)
        access=self.db.company_access_map(uid)
        for i in range(self.listAccess.count()):
            it=self.listAccess.item(i); it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in access else Qt.Unchecked)
        perm_map=self.db.user_perm_map(uid)
        for i in range(self.listPerm.count()):
            it=self.listPerm.item(i); it.setCheckState(Qt.Checked if perm_map.get(it.data(Qt.UserRole), False) else Qt.Unchecked)

    def add(self):
        r=self.table.rowCount(); self.table.insertRow(r); self.table.setItem(r,0,QTableWidgetItem(""))
        self.table.setItem(r,3,QTableWidgetItem("0")); self.table.setItem(r,4,QTableWidgetItem("1"))

    def save(self):
        for r in range(self.table.rowCount()):
            id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
            rec=dict(
                name=self.table.item(r,1).text() if self.table.item(r,1) else "",
                username=self.table.item(r,2).text() if self.table.item(r,2) else "",
                is_admin=1 if (self.table.item(r,3) and self.table.item(r,3).text() not in ("0","False","false")) else 0,
                active=1 if (self.table.item(r,4) and self.table.item(r,4).text() not in ("0","False","false")) else 0
            )
            if not rec["name"] or not rec["username"]: msg_err("Nome e Usuário são obrigatórios."); return
            uid=int(id_txt) if id_txt.strip().isdigit() else None
            uid=self.db.user_save(rec, uid); self.table.setItem(r,0,QTableWidgetItem(str(uid)))
            # salvar acessos/permissões do usuário selecionado
            if r == self.table.currentRow():
                access_ids=[self.listAccess.item(i).data(Qt.UserRole) for i in range(self.listAccess.count()) if self.listAccess.item(i).checkState()==Qt.Checked]
                perm_ids=[self.listPerm.item(i).data(Qt.UserRole) for i in range(self.listPerm.count()) if self.listPerm.item(i).checkState()==Qt.Checked]
                self.db.set_company_access(uid, access_ids)
                self.db.set_user_permissions(uid, set(perm_ids))
        msg_info("Usuários salvos."); self.load()

    def delete(self):
        r=self.table.currentRow()
        if r<0: return
        id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
        if not id_txt.strip().isdigit(): self.table.removeRow(r); return
        auth=AdminAuthDialog(self.db, self)
        if not (auth.exec_() and auth.ok): return
        if not msg_yesno("Excluir este usuário?"): return
        try: self.db.user_delete(int(id_txt))
        except sqlite3.IntegrityError as e: msg_err(str(e)); return
        self.load()

    def set_password(self):
        r=self.table.currentRow()
        if r<0: return
        id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
        if not id_txt.strip().isdigit(): msg_err("Salve o usuário antes de definir a senha."); return
        uid=int(id_txt)
        dlg=QDialog(self); dlg.setWindowTitle("Definir Senha"); form=QFormLayout(dlg)
        p1=QLineEdit(); p1.setEchoMode(QLineEdit.Password); p2=QLineEdit(); p2.setEchoMode(QLineEdit.Password)
        form.addRow("Senha:", p1); form.addRow("Confirmar:", p2)
        bt=QPushButton("Aplicar"); bt.clicked.connect(dlg.accept); form.addRow(bt)
        enable_autosize(dlg, 0.35, 0.3, 420, 240)
        if dlg.exec_():
            if not p1.text() or p1.text()!=p2.text(): msg_err("Senhas não conferem."); return
            self.db.user_set_password(uid, p1.text()); msg_info("Senha atualizada.")

class BanksDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.setWindowTitle("Cadastro de Bancos / Contas")

        # Agora são 9 colunas (sem 'Nome da Conta')
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "ID", "Banco", "Tipo", "Agência", "Conta",
            "Saldo Inicial", "Saldo Atual", "Ativo", "Criado em"
        ])
        stretch_table(self.table)
        zebra_table(self.table)
        self.table.setColumnHidden(0, True)

        # 'Tipo' com opções fixas
        self.table.setItemDelegateForColumn(2, AccountTypeDelegate(self))

        # Botões
        btAdd  = QPushButton("Novo")
        btSave = QPushButton("Salvar")
        btDel  = QPushButton("Excluir")
        btReload = QPushButton("Recarregar")
        for b, ic in (
            (btAdd, self.style().SP_FileDialogNewFolder),
            (btSave, self.style().SP_DialogSaveButton),
            (btDel, self.style().SP_TrashIcon),
            (btReload, self.style().SP_BrowserReload),
        ):
            b.setIcon(std_icon(self, ic))
        btAdd.clicked.connect(self.add)
        btSave.clicked.connect(self.save)
        btDel.clicked.connect(self.delete)
        btReload.clicked.connect(self.load)

        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        hl = QHBoxLayout()
        [hl.addWidget(b) for b in (btAdd, btSave, btDel, btReload)]
        lay.addLayout(hl)

        self.load()
        enable_autosize(self, 0.7, 0.55, 900, 520)

    def load(self):
        rows = self.db.banks(self.company_id)
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            # Sem 'account_name'; 'Tipo' é account_type
            data = [
                r["id"],
                r["bank_name"],
                (r["account_type"] or "CORRENTE"),
                r["agency"],
                r["account_number"],
                fmt_brl(r["initial_balance"]),
                fmt_brl(r["current_balance"]),
                r["active"],
                iso_to_br(str(r["created_at"])[:10]),
            ]
            for c, val in enumerate(data):
                it = QTableWidgetItem("" if val is None else str(val))
                # Tornar não editáveis: ID, Saldo Atual, Criado em
                if c in (0, 6, 8):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, c, it)

    def add(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))                    # ID vazio
        self.table.setItem(r, 2, QTableWidgetItem("CORRENTE"))            # Tipo padrão
        self.table.setItem(r, 6, QTableWidgetItem(fmt_brl(0)))            # Saldo Atual (read-only)
        self.table.setItem(r, 7, QTableWidgetItem("1"))                   # Ativo=1

        # Bloqueia edição das colunas travadas da nova linha também
        for c in (6, 8):
            it = self.table.item(r, c)
            if it:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)

    def save(self):
        for r in range(self.table.rowCount()):
            id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            rec = dict(
                bank_name     = self.table.item(r, 1).text() if self.table.item(r, 1) else "",
                account_name  = "",  # removido da UI; mantemos vazio para o método bank_save
                account_type  = (self.table.item(r, 2).text() if self.table.item(r, 2) else "CORRENTE").upper(),
                agency        = self.table.item(r, 3).text() if self.table.item(r, 3) else "",
                account_number= self.table.item(r, 4).text() if self.table.item(r, 4) else "",
                initial_balance = parse_brl(self.table.item(r, 5).text() if self.table.item(r, 5) else "0"),
                current_balance = parse_brl(self.table.item(r, 6).text() if self.table.item(r, 6) else "0"),
                active        = 1 if (self.table.item(r, 7) and self.table.item(r, 7).text() not in ("0","False","false")) else 0,
            )

            bid = int(id_txt) if id_txt.strip().isdigit() else None
            bid = self.db.bank_save(self.company_id, rec, bid)
            self.table.setItem(r, 0, QTableWidgetItem(str(bid)))

        msg_info("Bancos salvos.")
        self.load()

    def delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
        if not id_txt.strip().isdigit():
            self.table.removeRow(r)
            return
        if not msg_yesno("Excluir esta conta bancária?"):
            return
        try:
            self.db.bank_delete(int(id_txt))
        except sqlite3.IntegrityError as e:
            msg_err(f"Não foi possível excluir. Conta vinculada a pagamentos.\n{e}")
            return
        self.load()

class EntitiesDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.setWindowTitle("Cadastro de Fornecedor / Cliente")

        self.table = QTableWidget(0, 13)
        self.table.setHorizontalHeaderLabels([
            "ID","Tipo","CNPJ/CPF","Razão/Nome","Contato1","Contato2",
            "Rua","Bairro","Nº","CEP","UF","Cidade","Email"
        ])
        stretch_table(self.table); zebra_table(self.table)
        self.table.setColumnHidden(0, True)

        # Delegates
        self.table.setItemDelegateForColumn(1, KindComboDelegate(self))
        self.table.setItemDelegateForColumn(2, DocNumberDelegate(self))
        self.table.setItemDelegateForColumn(9, MaskDelegate(mask="00000-000", parent=self))
        self.table.setItemDelegateForColumn(10, MaskDelegate(regex=r"[A-Za-z]{0,2}", uppercase=True, parent=self))

        # >>> Ordenação pelo cabeçalho
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.setSortIndicatorShown(True)
        self.table.setSortingEnabled(True)

        # Botões
        btAdd = QPushButton("Novo")
        btSave = QPushButton("Salvar")
        btDel = QPushButton("Excluir")
        btReload = QPushButton("Recarregar")
        for b, ic in (
            (btAdd, self.style().SP_FileDialogNewFolder),
            (btSave, self.style().SP_DialogSaveButton),
            (btDel, self.style().SP_TrashIcon),
            (btReload, self.style().SP_BrowserReload),
        ):
            b.setIcon(std_icon(self, ic))
        btAdd.clicked.connect(self.add)
        btSave.clicked.connect(self.save)
        btDel.clicked.connect(self.delete)
        btReload.clicked.connect(self.load)

        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        hl = QHBoxLayout(); [hl.addWidget(b) for b in (btAdd, btSave, btDel, btReload)]
        lay.addLayout(hl)

        self.load()
        enable_autosize(self, 0.85, 0.75, 1100, 650)

    def load(self):
        rows = self.db.entities(self.company_id)
        # desabilita ordenação durante o preenchimento para acelerar e não reordenar no meio
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)

        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # formatações de exibição
            doc = r["cnpj_cpf"] or ""
            d = only_digits(doc)
            if len(d) == 11: doc = format_cpf(d)
            elif len(d) == 14: doc = format_cnpj(d)

            cep = r["cep"] or ""
            if cep:
                dcep = only_digits(cep)
                cep = f"{dcep[:5]}-{dcep[5:]}" if len(dcep) == 8 else cep

            data = [
                r["id"], r["kind"], doc, r["razao_social"], r["contato1"], r["contato2"],
                r["rua"], r["bairro"], r["numero"], cep, (r["uf"] or ""), r["cidade"], r["email"]
            ]

            for c, val in enumerate(data):
                txt = "" if val is None else str(val)
                it = QTableWidgetItem(txt)
                if c == 0:  # ID não editável
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)

                # --- CNPJ/CPF (ordenar pelos dígitos numéricos)
                if c == 2:
                    dig = only_digits(txt)
                    if dig.isdigit():
                        it.setData(Qt.UserRole, int(dig))   # chave de ordenação
                        it.setData(Qt.EditRole, int(dig))   # PyQt5 usa EditRole na ordenação

                # --- Nº (numérico)
                elif c == 8:
                    try:
                        n = int(txt)
                        it.setData(Qt.UserRole, n)
                        it.setData(Qt.EditRole, n)
                    except Exception:
                        pass

                # --- CEP (ordenar pelos dígitos)
                elif c == 9:
                    dig = only_digits(txt)
                    if dig.isdigit():
                        it.setData(Qt.UserRole, int(dig))
                        it.setData(Qt.EditRole, int(dig))
                self.table.setItem(row, c, it)

        # reabilita ordenação
        self.table.setSortingEnabled(was_sorting)

    def add(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))              # ID vazio
        self.table.setItem(r, 1, QTableWidgetItem("FORNECEDOR"))    # tipo padrão

    def save(self):
        for r in range(self.table.rowCount()):
            id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            kind = (self.table.item(r, 1).text() if self.table.item(r, 1) else "FORNECEDOR").upper()
            if kind not in ("FORNECEDOR", "CLIENTE", "AMBOS"):
                kind = "FORNECEDOR"


            doc = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            d = only_digits(doc)
            if d:
                if len(d) == 11 and not validate_cpf(d): msg_err(f"CPF inválido (linha {r+1})."); return
                if len(d) == 14 and not validate_cnpj(d): msg_err(f"CNPJ inválido (linha {r+1})."); return
                if len(d) not in (11, 14): msg_err(f"Documento deve ter 11 (CPF) ou 14 (CNPJ) dígitos (linha {r+1})."); return

            cep = self.table.item(r, 9).text() if self.table.item(r, 9) else ""
            uf = self.table.item(r,10).text().upper() if self.table.item(r,10) else ""
            if cep and not validate_cep(cep): msg_err(f"CEP inválido (linha {r+1})."); return
            if uf and not validate_uf(uf): msg_err(f"UF inválida (linha {r+1})."); return

            rec = dict(
                kind=kind, cnpj_cpf=d,
                razao_social=self.table.item(r,3).text() if self.table.item(r,3) else "",
                contato1=self.table.item(r,4).text() if self.table.item(r,4) else "",
                contato2=self.table.item(r,5).text() if self.table.item(r,5) else "",
                rua=self.table.item(r,6).text() if self.table.item(r,6) else "",
                bairro=self.table.item(r,7).text() if self.table.item(r,7) else "",
                numero=self.table.item(r,8).text() if self.table.item(r,8) else "",
                cep=only_digits(cep), uf=uf,
                cidade=self.table.item(r,11).text() if self.table.item(r,11) else "",
                email=self.table.item(r,12).text() if self.table.item(r,12) else "",
                active=1
            )
            if not rec["razao_social"]:
                msg_err("Razão/Nome é obrigatório."); return

            eid = int(id_txt) if id_txt.strip().isdigit() else None
            eid = self.db.entity_save(self.company_id, rec, eid)
            self.table.setItem(r, 0, QTableWidgetItem(str(eid)))

        msg_info("Registros salvos.")
        self.load()

    def delete(self):
        r = self.table.currentRow()
        if r < 0: return
        id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
        if not id_txt.strip().isdigit():
            self.table.removeRow(r); return
        if not msg_yesno("Excluir este cadastro?"): return
        try:
            self.db.entity_delete(int(id_txt))
        except sqlite3.IntegrityError as e:
            msg_err(f"Não foi possível excluir. Existem lançamentos vinculados.\n{e}")
            return
        self.load()

class CategoriesDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.setWindowTitle("Cadastro de Categorias e Subcategorias")

        # filtro tipo
        self.cbTipo = QComboBox()
        self.cbTipo.addItems(["PAGAR", "RECEBER"])
        self.cbTipo.currentIndexChanged.connect(self.load)

        top = QHBoxLayout()
        top.addWidget(QLabel("Tipo:"))
        top.addWidget(self.cbTipo)
        top.addStretch()

        # tabela categorias
        self.tblCat = QTableWidget(0, 3)
        self.tblCat.setHorizontalHeaderLabels(["ID", "Categoria", "Tipo"])
        stretch_table(self.tblCat)
        zebra_table(self.tblCat)
        self.tblCat.setColumnHidden(0, True)
        self.tblCat.currentCellChanged.connect(self.load_subs)

        # tabela subcategorias
        self.tblSub = QTableWidget(0, 2)
        self.tblSub.setHorizontalHeaderLabels(["ID", "Subcategoria"])
        stretch_table(self.tblSub)
        zebra_table(self.tblSub)
        self.tblSub.setColumnHidden(0, True)

        # botões
        btAddC = QPushButton("Nova Categoria")
        btSaveC = QPushButton("Salvar Cat.")
        btDelC = QPushButton("Excluir Cat.")

        btAddS = QPushButton("Nova Subcat.")
        btSaveS = QPushButton("Salvar Sub.")
        btDelS = QPushButton("Excluir Sub.")

        for b, ic in (
            (btAddC, self.style().SP_FileDialogNewFolder),
            (btSaveC, self.style().SP_DialogSaveButton),
            (btDelC, self.style().SP_TrashIcon),
            (btAddS, self.style().SP_FileDialogNewFolder),
            (btSaveS, self.style().SP_DialogSaveButton),
            (btDelS, self.style().SP_TrashIcon),
        ):
            b.setIcon(std_icon(self, ic))

        btAddC.clicked.connect(self.add_cat)
        btSaveC.clicked.connect(self.save_cat_and_subs)   # salva cat + subs
        btDelC.clicked.connect(self.del_cat)

        btAddS.clicked.connect(self.add_sub)
        btSaveS.clicked.connect(self.save_sub)            # salva subs (e salva cat se precisar)
        btDelS.clicked.connect(self.del_sub)

        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(self.tblCat)
        lc = QHBoxLayout()
        [lc.addWidget(b) for b in (btAddC, btSaveC, btDelC)]
        left.addLayout(lc)

        right = QVBoxLayout()
        right.addWidget(self.tblSub)
        rs = QHBoxLayout()
        [rs.addWidget(b) for b in (btAddS, btSaveS, btDelS)]
        right.addLayout(rs)

        main = QHBoxLayout(self)
        main.addLayout(left, 3)
        main.addLayout(right, 2)

        self.load()
        enable_autosize(self, 0.85, 0.75, 1100, 650)

    # ----------------- carregamento -----------------
    def load(self):
        tipo = self.cbTipo.currentText()
        rows = self.db.categories(self.company_id, tipo)
        self.tblCat.setRowCount(0)
        self.tblSub.setRowCount(0)
        for r in rows:
            row = self.tblCat.rowCount()
            self.tblCat.insertRow(row)
            for c, val in enumerate([r["id"], r["name"], r["tipo"]]):
                it = QTableWidgetItem("" if val is None else str(val))
                if c == 0:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.tblCat.setItem(row, c, it)
        if rows:
            self.tblCat.selectRow(0)
            self.load_subs(0, 0, 0, 0)

    def load_subs(self, *args):
        r = self.tblCat.currentRow()
        self.tblSub.setRowCount(0)
        if r < 0:
            return
        id_txt = self.tblCat.item(r, 0).text() if self.tblCat.item(r, 0) else ""
        if not id_txt.strip().isdigit():
            return
        for s in self.db.subcategories(int(id_txt)):
            row = self.tblSub.rowCount()
            self.tblSub.insertRow(row)
            it0 = QTableWidgetItem(str(s["id"]))
            it0.setFlags(it0.flags() & ~Qt.ItemIsEditable)
            self.tblSub.setItem(row, 0, it0)
            self.tblSub.setItem(row, 1, QTableWidgetItem(s["name"]))

    # ----------------- helpers -----------------
    def _current_cat_row(self):
        return self.tblCat.currentRow()

    def _current_cat_fields(self):
        """Retorna (row, id_txt, name, tipo)."""
        row = self._current_cat_row()
        if row < 0:
            return -1, "", "", self.cbTipo.currentText()
        id_txt = self.tblCat.item(row, 0).text() if self.tblCat.item(row, 0) else ""
        name = self.tblCat.item(row, 1).text() if self.tblCat.item(row, 1) else ""
        tipo = self.tblCat.item(row, 2).text() if self.tblCat.item(row, 2) else self.cbTipo.currentText()
        return row, id_txt, name.strip(), (tipo or self.cbTipo.currentText())

    def _ensure_current_category_saved(self):
        """
        Garante que a categoria atual possua ID no banco.
        - Se já tem ID, retorna int(ID).
        - Se não tem, salva e devolve o novo ID (sem recarregar a tela).
        """
        row, id_txt, name, tipo = self._current_cat_fields()
        if row < 0:
            msg_err("Selecione ou crie uma categoria.")
            return None
        if id_txt.strip().isdigit():
            return int(id_txt)
        if not name:
            msg_err("Informe o nome da categoria antes de salvar a subcategoria.")
            return None
        try:
            cid = self.db.category_save(self.company_id, name, tipo, None)
            self.tblCat.setItem(row, 0, QTableWidgetItem(str(cid)))
            return cid
        except sqlite3.IntegrityError as e:
            msg_err("Não foi possível salvar a categoria (duplicada?).")
            return None

    # ----------------- ações categorias -----------------
    def add_cat(self):
        r = self.tblCat.rowCount()
        self.tblCat.insertRow(r)
        self.tblCat.setItem(r, 0, QTableWidgetItem(""))  # ID vazio
        self.tblCat.setItem(r, 1, QTableWidgetItem(""))  # nome
        self.tblCat.setItem(r, 2, QTableWidgetItem(self.cbTipo.currentText()))
        self.tblCat.selectRow(r)
        self.tblSub.setRowCount(0)

    def save_cat(self):
        """Salva todas as categorias listadas."""
        ok_any = False
        for r in range(self.tblCat.rowCount()):
            id_txt = self.tblCat.item(r, 0).text() if self.tblCat.item(r, 0) else ""
            name = self.tblCat.item(r, 1).text().strip() if self.tblCat.item(r, 1) else ""
            tipo = self.tblCat.item(r, 2).text().strip() if self.tblCat.item(r, 2) else self.cbTipo.currentText()
            if not name:
                continue
            cid = int(id_txt) if id_txt.strip().isdigit() else None
            try:
                cid = self.db.category_save(self.company_id, name, tipo, cid)
                self.tblCat.setItem(r, 0, QTableWidgetItem(str(cid)))
                ok_any = True
            except sqlite3.IntegrityError:
                msg_err(f"Categoria '{name}' já existe para este tipo.")
                return False
        if ok_any:
            return True
        return False

    def save_cat_and_subs(self):
        """Botão 'Salvar Cat.' também salva subcategorias da categoria atual."""
        if not self.save_cat():
            return
        # salva as subs da categoria selecionada
        self.save_sub(show_msg=False)
        msg_info("Categorias e subcategorias salvas.")
        # Recarrega a lista de subcategorias da categoria atual
        self.load_subs()

    def del_cat(self):
        r = self.tblCat.currentRow()
        if r < 0:
            return
        id_txt = self.tblCat.item(r, 0).text() if self.tblCat.item(r, 0) else ""
        if not id_txt.strip().isdigit():
            self.tblCat.removeRow(r)
            self.tblSub.setRowCount(0)
            return
        if not msg_yesno("Excluir esta categoria e suas subcategorias?"):
            return
        try:
            self.db.category_delete(int(id_txt))
        except sqlite3.IntegrityError as e:
            msg_err("Não foi possível excluir. Existem lançamentos vinculados.\n" + str(e))
            return
        self.load()

    # ----------------- ações subcategorias -----------------
    def add_sub(self):
        if self._current_cat_row() < 0:
            msg_err("Selecione uma categoria.")
            return
        r = self.tblSub.rowCount()
        self.tblSub.insertRow(r)
        self.tblSub.setItem(r, 0, QTableWidgetItem(""))   # ID vazio
        self.tblSub.setItem(r, 1, QTableWidgetItem(""))   # NOME (criado agora para permitir digitar)
        self.tblSub.editItem(self.tblSub.item(r, 1))

    def save_sub(self, show_msg=True):
        """
        Salva todas as subcategorias da categoria atual.
        - Se a categoria ainda não existir no banco, salva primeiro e usa o novo ID.
        """
        cat_id = self._ensure_current_category_saved()
        if not cat_id:
            return

        any_saved = False
        for r in range(self.tblSub.rowCount()):
            id_txt = self.tblSub.item(r, 0).text() if self.tblSub.item(r, 0) else ""
            name = self.tblSub.item(r, 1).text().strip() if self.tblSub.item(r, 1) else ""
            if not name:
                continue
            sid = int(id_txt) if id_txt.strip().isdigit() else None
            try:
                sid = self.db.subcategory_save(cat_id, name, sid)
                self.tblSub.setItem(r, 0, QTableWidgetItem(str(sid)))
                any_saved = True
            except sqlite3.IntegrityError:
                msg_err(f"Subcategoria '{name}' já existe nesta categoria.")
                return

        if show_msg and any_saved:
            msg_info("Subcategorias salvas.")
        # Recarrega para refletir o que ficou gravado
        self.load_subs()

    def del_sub(self):
        r = self.tblSub.currentRow()
        if r < 0:
            return
        id_txt = self.tblSub.item(r, 0).text() if self.tblSub.item(r, 0) else ""
        if not id_txt.strip().isdigit():
            self.tblSub.removeRow(r)
            return
        if not msg_yesno("Excluir esta subcategoria?"):
            return
        try:
            self.db.subcategory_delete(int(id_txt))
        except sqlite3.IntegrityError as e:
            msg_err("Não foi possível excluir. Há lançamentos vinculados.\n" + str(e))
            return
        self.load_subs()

# =============================================================================
# Pagamentos / Lançamentos / Fluxo / DRE
# =============================================================================
class PaymentDialog(QDialog):
    def __init__(self, db: DB, company_id, tx, user_id, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id; self.tx=tx; self.user_id=user_id
        self.setWindowTitle("Liquidar Lançamento")
        form=QFormLayout(self)
        self.dt=QDateEdit(QDate.currentDate()); set_br_date(self.dt)
        self.cbBank=QComboBox()
        for b in self.db.banks(company_id):
            self.cbBank.addItem(f"{b['bank_name']} - {b['account_name'] or ''}", b["id"])
        faltante=max(0.0, float(tx["valor"]) - float(tx["pago"]))
        self.edValor=BRLCurrencyLineEdit(); self.edValor.setValue(faltante)
        self.edJuros=BRLCurrencyLineEdit(); self.edJuros.setValue(0.0)
        self.edDesc=BRLCurrencyLineEdit(); self.edDesc.setValue(0.0)
        self.edDoc=QLineEdit()
        form.addRow("Data pagamento:", self.dt); form.addRow("Banco:", self.cbBank)
        form.addRow("Valor:", self.edValor); form.addRow("Juros:", self.edJuros)
        form.addRow("Desconto:", self.edDesc); form.addRow("Documento ref.:", self.edDoc)
        bt=QPushButton("Confirmar"); bt.setIcon(std_icon(self, self.style().SP_DialogApplyButton)); bt.clicked.connect(self.ok)
        form.addRow(bt); self.ok_clicked=False
        enable_autosize(self, 0.45, 0.4, 520, 360)
    def ok(self):
        try:
            rec=dict(transaction_id=self.tx["id"], company_id=self.company_id, payment_date=qdate_to_iso(self.dt.date()),
                     bank_id=self.cbBank.currentData(), amount=self.edValor.value(), interest=self.edJuros.value(),
                     discount=self.edDesc.value(), doc_ref=self.edDoc.text(), created_by=self.user_id)
            self.db.payment_add(rec); self.ok_clicked=True; self.accept()
        except sqlite3.IntegrityError as e:
            msg_err(str(e), self)

def set_combo_by_data(cb: QComboBox, value):
    idx = cb.findData(value)
    if idx >= 0:
        cb.setCurrentIndex(idx)

# ======== SUBSTITUA A CLASSE TransactionsDialog INTEIRA POR ESTA ============
class TransactionsDialog(QDialog):
    data_changed = pyqtSignal()  # notifica o dashboard

    # --------------------------- helpers visuais ---------------------------
    def _search_combo_with_button(self, with_button: bool = True):
        """
        Retorna (wrap, combo, btn). Quando with_button=False, não cria o botão,
        ficando só o QComboBox (sem ícone).
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        combo = QComboBox(self)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        btn = None
        if with_button:
            btn = QPushButton("", self)
            btn.setFixedSize(28, 28)
            btn.setIcon(std_icon(self, self.style().SP_FileDialogContentsView))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            row.addWidget(combo, 1)
            row.addWidget(btn, 0)
        else:
            row.addWidget(combo, 1)

        wrap = QWidget(self)
        wrap.setLayout(row)
        return wrap, combo, btn

    # ------------------------------- init ---------------------------------
    def __init__(self, db: DB, company_id: int, user_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.user_id = user_id
        self.current_tx_id = None
        self._rows_by_id = {}

        self.setWindowTitle("Lançamentos")

        # ---------- TOPO: título ----------
        outer = QVBoxLayout(self)
        title = QLabel("✓ Lançamentos")
        f = title.font()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        outer.addWidget(title)

        # ===================== LINHA SUPERIOR (form + tipo) =====================
        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        outer.addLayout(top_row)

        # ---------------------- FORM PRINCIPAL (ESQUERDA) ----------------------
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        # Fornecedor/Cliente (com botão)
        grid.addWidget(QLabel("Fornecedor/Cliente:"), 0, 0)
        forn_wrap, self.cbEnt, self.btFindEnt = self._search_combo_with_button(True)
        grid.addWidget(forn_wrap, 0, 1, 1, 3)

        # Datas
        grid.addWidget(QLabel("Data Lançamento:"), 0, 4)
        self.dtLanc = QDateEdit(QDate.currentDate())
        set_br_date(self.dtLanc)
        self.dtLanc.setFixedWidth(130)
        grid.addWidget(self.dtLanc, 0, 5)

        grid.addWidget(QLabel("Data Vencimento:"), 0, 6)
        self.dtVenc = QDateEdit(QDate.currentDate())
        set_br_date(self.dtVenc)
        self.dtVenc.setFixedWidth(130)
        grid.addWidget(self.dtVenc, 0, 7)

        # Categoria (SEM botão)
        grid.addWidget(QLabel("Categoria (Classificação da Conta):"), 1, 0, 1, 2)
        cat_wrap, self.cbCat, _ = self._search_combo_with_button(False)
        grid.addWidget(cat_wrap, 1, 2, 1, 6)

        # Subcategoria (SEM botão)
        grid.addWidget(QLabel("Subcategoria (Plano de Contas):"), 2, 0, 1, 2)
        sub_wrap, self.cbSub, _ = self._search_combo_with_button(False)
        grid.addWidget(sub_wrap, 2, 2, 1, 3)

        # Valor
        grid.addWidget(QLabel("Valor:"), 2, 5)
        self.edValor = BRLCurrencyLineEdit()
        self.edValor.setValue(0.0)
        grid.addWidget(self.edValor, 2, 6, 1, 2)

        # Forma / Parcelas
        grid.addWidget(QLabel("Forma de Pagamento:"), 3, 0, 1, 2)
        self.cbForma = QComboBox()
        self.cbForma.addItems(["Boleto", "PIX", "Transferência", "Dinheiro", "Cartão"])
        grid.addWidget(self.cbForma, 3, 2)

        grid.addWidget(QLabel("Quantidade de Parcelas:"), 3, 3)
        self.spParcelas = QSpinBox()
        self.spParcelas.setRange(1, 120)
        self.spParcelas.setValue(1)
        grid.addWidget(self.spParcelas, 3, 4)

        # Descrição (deixe 6 colunas para não colidir com o Status)
        grid.addWidget(QLabel("Descrição do Lançamento:"), 4, 0, 1, 6)
        self.edDesc = QTextEdit()
        self.edDesc.setFixedHeight(64)
        grid.addWidget(self.edDesc, 5, 0, 1, 6)

        # Status (apenas display) + Banco
        grid.addWidget(QLabel("Status:"), 5, 6)
        self.btnStatus = QPushButton("EM ABERTO")
        self.btnStatus.setMinimumHeight(34)
        self.btnStatus.setEnabled(False)
        grid.addWidget(self.btnStatus, 5, 7)

        grid.addWidget(QLabel("Banco:"), 6, 0)
        self.cbBanco = QComboBox()
        self.cbBanco.setFixedWidth(220)
        grid.addWidget(self.cbBanco, 6, 1)

        # Botões de ação (LIQUIDAR / CANCELAR / EDITAR)
        self.btLiquidar = QPushButton("LIQUIDAR")
        self.btCancelar = QPushButton("CANCELAR")
        self.btEditarLinha = QPushButton("EDITAR")
        act = QHBoxLayout()
        act.setSpacing(8)
        for b, ic in (
            (self.btLiquidar, self.style().SP_DialogApplyButton),
            (self.btCancelar, self.style().SP_DialogCancelButton),
            (self.btEditarLinha, self.style().SP_FileDialogDetailedView),
        ):
            b.setIcon(std_icon(self, ic))
            b.setMinimumHeight(34)
            act.addWidget(b)
        act.addStretch(1)
        grid.addLayout(act, 6, 2, 1, 6)

        left_wrap = QWidget()
        left_wrap.setLayout(grid)
        top_row.addWidget(left_wrap, 2)

        # ---------------------- COLUNA DIREITA (TIPO + SALDOS) -----------------
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        grpTipo = QGroupBox("Tipo do cadastro")
        v = QVBoxLayout(grpTipo)
        self.rbPagar = QRadioButton("Contas a Pagar")
        self.rbReceber = QRadioButton("Contas a Receber")
        self.rbPagar.setChecked(True)
        v.addWidget(self.rbPagar)
        v.addWidget(self.rbReceber)
        right_col.addWidget(grpTipo)

        grpSaldo = QGroupBox("")
        g = QGridLayout(grpSaldo)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        g.addWidget(QLabel("Banco:"), 0, 0)
        self.cmbSaldoBanco = QComboBox()
        g.addWidget(self.cmbSaldoBanco, 0, 1)
        g.addWidget(QLabel("Saldo Total Geral:"), 1, 0)
        self.edSaldoGeral = QLineEdit()
        self.edSaldoGeral.setAlignment(Qt.AlignRight)
        self.edSaldoGeral.setReadOnly(True)
        g.addWidget(self.edSaldoGeral, 1, 1)
        g.addWidget(QLabel("Saldo por Banco:"), 2, 0)
        self.edSaldoBanco = QLineEdit()
        self.edSaldoBanco.setAlignment(Qt.AlignRight)
        self.edSaldoBanco.setReadOnly(True)
        g.addWidget(self.edSaldoBanco, 2, 1)
        right_col.addWidget(grpSaldo)

        right_col.addStretch(1)
        right_wrap = QWidget()
        right_wrap.setLayout(right_col)
        top_row.addWidget(right_wrap, 1)

        # ================================ TABELA ================================
        self.table = QTableWidget(0, 14)
        headers = [
            "Status",
            "Forma de Pagamento",
            "Valor",
            "Juros",
            "Data Liquidação",
            "Data Vencimento",
            "Parcelas",
            "Banco",
            "Fornecedor/Cliente",
            "Categoria",
            "Subcategoria",
            "Data Lançamento",
            "Tipo",
            "ID",
        ]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setMinimumHeight(300)
        self.table.setColumnHidden(13, True)  # esconde ID

        table_row = QHBoxLayout()
        table_row.addWidget(self.table, 1)
        self.btAbrir = QPushButton("ABRIR")
        self.btAbrir.setIcon(std_icon(self, self.style().SP_DialogOpenButton))
        side = QVBoxLayout()
        side.addStretch(1)
        side.addWidget(self.btAbrir)
        table_row.addLayout(side)
        outer.addLayout(table_row)

        # ============================ FILTROS INFERIORES ========================
        filtros = QGridLayout()
        filtros.setHorizontalSpacing(10)
        filtros.setVerticalSpacing(10)
        filtros.addWidget(QLabel("Informe Período:"), 0, 0)
        filtros.addWidget(QLabel("Início:"), 0, 1)
        self.filIni = QDateEdit(QDate.currentDate().addMonths(-1))
        set_br_date(self.filIni)
        filtros.addWidget(self.filIni, 0, 2)
        filtros.addWidget(QLabel("Final:"), 0, 3)
        self.filFim = QDateEdit(QDate.currentDate())
        set_br_date(self.filFim)
        filtros.addWidget(self.filFim, 0, 4)

        filtros.addWidget(QLabel("Tipo do cadastro"), 0, 5)
        self.cbTipoFiltro = QComboBox()
        self.cbTipoFiltro.addItems(["", "Contas a Pagar", "Contas a Receber"])
        filtros.addWidget(self.cbTipoFiltro, 0, 6)

        filtros.addWidget(QLabel("Status:"), 0, 7)
        self.cbStatusFiltro = QComboBox()
        self.cbStatusFiltro.addItems(["", "EM ABERTO", "LIQUIDADO", "CANCELADO"])
        filtros.addWidget(self.cbStatusFiltro, 0, 8)

        filtros.addWidget(QLabel("Fornecedor/Cliente"), 1, 0, 1, 2)
        fornF_wrap, self.filForn, _ = self._search_combo_with_button(True)
        filtros.addWidget(fornF_wrap, 1, 2, 1, 4)

        filtros.addWidget(QLabel("Categoria"), 1, 6)
        self.cbCatFiltro = QComboBox()
        filtros.addWidget(self.cbCatFiltro, 1, 7)

        self.btPesquisar = QPushButton("PESQUISAR")
        self.btPesquisar.setIcon(std_icon(self, self.style().SP_FileDialogContentsView))
        filtros.addWidget(self.btPesquisar, 1, 8)

        outer.addLayout(filtros)

        # ================================ RODAPÉ ================================
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.btNovo = QPushButton("  NOVO")
        self.btNovo.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        self.btSalvar = QPushButton("  SALVAR")
        self.btSalvar.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        self.btEditar = QPushButton("  EDITAR")
        self.btEditar.setIcon(std_icon(self, self.style().SP_FileDialogDetailedView))
        self.btExcluir = QPushButton("  EXCLUIR")
        self.btExcluir.setIcon(std_icon(self, self.style().SP_TrashIcon))
        for b in (self.btNovo, self.btSalvar, self.btEditar, self.btExcluir):
            b.setMinimumHeight(34)
        foot.addWidget(self.btNovo)
        foot.addWidget(self.btSalvar)
        foot.addWidget(self.btEditar)
        foot.addWidget(self.btExcluir)
        foot.addStretch(1)
        btFechar = QPushButton("  FECHAR")
        btFechar.setIcon(std_icon(self, self.style().SP_DialogCloseButton))
        btFechar.clicked.connect(self.close)
        foot.addWidget(btFechar)
        outer.addLayout(foot)

        # -------- estilos leves --------
        self.setStyleSheet(
            """
        QGroupBox {
            font-weight: bold; border: 1px solid #D6D6D6; border-radius: 8px;
            margin-top: 8px; padding: 8px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 2px; }
        QPushButton { border: 1px solid #d0d0d0; border-radius: 8px; padding: 6px 12px; background: #f7f7f7; }
        QPushButton:hover { background: #f0f0f0; }
        QTableWidget { gridline-color: #e2e2e2; }
        QHeaderView::section { background: #f2f2f2; padding: 6px; border: 1px solid #e0e0e0; }
        """
        )

        # ====== conexões ======
        self.rbPagar.toggled.connect(self.on_tipo_changed)
        self.rbReceber.toggled.connect(self.on_tipo_changed)
        self.btNovo.clicked.connect(self.new)
        self.btSalvar.clicked.connect(self.save)
        self.btEditar.clicked.connect(self.edit_selected)
        self.btAbrir.clicked.connect(self.edit_selected)
        self.btExcluir.clicked.connect(self.delete)
        self.btLiquidar.clicked.connect(self.liquidar)
        self.btCancelar.clicked.connect(self.cancel_selected)
        self.btPesquisar.clicked.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self._update_status_from_selection)
        self.cbCat.currentIndexChanged.connect(self._load_subcategories_for_form)
        if self.btFindEnt:
            self.btFindEnt.clicked.connect(self._open_entities_and_refresh)

        self.cmbSaldoBanco.currentIndexChanged.connect(self._refresh_saldos)

        self.populate_static()
        self.load()  # carrega a grade

        # Tamanho inicial pré-definido, mas ainda redimensionável
        self.resize(1220, 640)
        try:
            self.setSizeGripEnabled(True)
        except Exception:
            pass
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

    # --------------------------- dados estáticos ---------------------------
    def populate_static(self):
        # bancos (form + painel saldo)
        self.cbBanco.blockSignals(True)
        self.cbBanco.clear()
        self.cmbSaldoBanco.blockSignals(True)
        self.cmbSaldoBanco.clear()
        total = 0.0
        for b in self.db.banks(self.company_id):
            label = f"{b['bank_name']} - {b['account_name'] or ''}"
            self.cbBanco.addItem(label, b["id"])
            self.cmbSaldoBanco.addItem(label, b["id"])
            try:
                total += float(b["current_balance"])
            except Exception:
                pass
        self.cbBanco.blockSignals(False)
        self.cmbSaldoBanco.insertItem(0, "", None)
        self.cmbSaldoBanco.setCurrentIndex(0)
        self.cmbSaldoBanco.blockSignals(False)
        self.edSaldoGeral.setText(fmt_brl(total))
        self.edSaldoBanco.setText("")

        # tipos (entidades/categorias dependem do tipo)
        self._refresh_entities_by_tipo()
        self._refresh_categories_by_tipo()
        self._load_subcategories_for_form()

        # filtros: fornecedor e categoria
        self._fill_filter_entities()
        self._fill_filter_categories()

    def _refresh_entities_by_tipo(self):
        kind = "FORNECEDOR" if self._current_tipo() == "PAGAR" else "CLIENTE"
        self.cbEnt.clear()
        ents = self.db.entities(self.company_id, kind=kind)
        self.cbEnt.addItem("", None)
        for e in ents:
            self.cbEnt.addItem(e["razao_social"], e["id"])

    def _refresh_categories_by_tipo(self):
        tipo = self._current_tipo()
        self.cbCat.clear()
        cats = self.db.categories(self.company_id, tipo=tipo)
        self.cbCat.addItem("", None)
        for c in cats:
            self.cbCat.addItem(c["name"], c["id"])

    def _load_subcategories_for_form(self):
        self.cbSub.clear()
        cat_id = self.cbCat.currentData()
        if not cat_id:
            self.cbSub.addItem("", None)
            return
        subs = self.db.subcategories(cat_id)
        self.cbSub.addItem("", None)
        for s in subs:
            self.cbSub.addItem(s["name"], s["id"])

    def _fill_filter_entities(self):
        # lista completa (independente do tipo) para facilitar filtro
        self.filForn.clear()
        self.filForn.addItem("", None)
        for e in self.db.entities(self.company_id):
            self.filForn.addItem(e["razao_social"], e["id"])

    def _fill_filter_categories(self):
        self.cbCatFiltro.clear()
        self.cbCatFiltro.addItem("", None)
        # mostra ambas (PAGAR/RECEBER) para filtro
        for t in ("PAGAR", "RECEBER"):
            for c in self.db.categories(self.company_id, t):
                label = f"{c['name']} [{t}]"
                self.cbCatFiltro.addItem(label, c["id"])

    def _refresh_saldos(self):
        # saldo total já preenchido em populate_static; aqui só por banco
        bank_id = self.cmbSaldoBanco.currentData()
        if not bank_id:
            self.edSaldoBanco.setText("")
            return
        row = next((b for b in self.db.banks(self.company_id) if b["id"] == bank_id), None)
        self.edSaldoBanco.setText(fmt_brl(row["current_balance"]) if row else "")

    def _open_entities_and_refresh(self):
        # abre cadastro para permitir criar/editar e depois recarrega combos
        EntitiesDialog(self.db, self.company_id, self).exec_()
        self._refresh_entities_by_tipo()
        self._fill_filter_entities()

    # --------------------------- util/estado --------------------------------
    def _current_tipo(self) -> str:
        return "PAGAR" if self.rbPagar.isChecked() else "RECEBER"

    def _rebuild_name_caches(self):
        self._ent_name = {r["id"]: r["razao_social"] for r in self.db.entities(self.company_id)}
        self._cat_name = {r["id"]: r["name"] for r in self.db.categories(self.company_id)}
        # sub precisa passar por todas categorias
        self._sub_name = {}
        for cid in self._cat_name.keys():
            for s in self.db.subcategories(cid):
                self._sub_name[s["id"]] = s["name"]
        self._bank_name = {
            r["id"]: f"{r['bank_name']} - {r['account_name'] or ''}" for r in self.db.banks(self.company_id)
        }

    # ------------------------------- carregar -------------------------------
    def load(self):
        self.apply_filters()

    def apply_filters(self):
        self._rebuild_name_caches()
        self.table.setRowCount(0)
        self._rows_by_id = {}

        dt_ini = qdate_to_iso(self.filIni.date())
        dt_fim = qdate_to_iso(self.filFim.date())
        tipo_sel = self.cbTipoFiltro.currentText()
        tipo = None
        if tipo_sel == "Contas a Pagar":
            tipo = "PAGAR"
        elif tipo_sel == "Contas a Receber":
            tipo = "RECEBER"

        rows = self.db.transactions(self.company_id, tipo)
        ent_filter = self.filForn.currentData()
        cat_filter = self.cbCatFiltro.currentData()
        status_filter = self.cbStatusFiltro.currentText() or ""

        for t in rows:
            # período por vencimento
            dv = str(t["data_venc"])
            if not (dt_ini <= dv <= dt_fim):
                continue

            # calcula status visual
            valor = float(t["valor"] or 0.0)
            pago = float(t["pago"] or 0.0)
            status = t["status"]
            if status != "CANCELADO" and pago >= valor - 1e-6:
                status = "LIQUIDADO"

            # filtros adicionais
            if ent_filter and t["entity_id"] != ent_filter:
                continue
            if cat_filter and t["category_id"] != cat_filter:
                continue
            if status_filter and status != status_filter:
                continue

            # juros total e data liquidação (busca rápida nos pagamentos)
            juros_total = 0.0
            data_liq = ""
            try:
                pays = self.db.payments_for(t["id"])
                if pays:
                    juros_total = sum(float(p["interest"] or 0.0) for p in pays)
                    if status == "LIQUIDADO":
                        # considera última data de pagamento
                        data_liq = max(str(p["payment_date"]) for p in pays)
            except Exception:
                pass

            row = self.table.rowCount()
            self.table.insertRow(row)

            def _set(r, c, text):
                it = QTableWidgetItem("" if text is None else str(text))
                if c in (2, 3):  # valores à direita
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)

            _set(row, 0, status)
            _set(row, 1, t["forma_pagto"] or "")
            _set(row, 2, fmt_brl(valor))
            _set(row, 3, fmt_brl(juros_total) if juros_total else "")
            _set(row, 4, iso_to_br(data_liq) if data_liq else "")
            _set(row, 5, iso_to_br(t["data_venc"]))
            _set(row, 6, t["parcelas_qtd"])
            _set(row, 7, self._bank_name.get(t["banco_id_padrao"], "") if t["banco_id_padrao"] else "")
            _set(row, 8, self._ent_name.get(t["entity_id"], ""))
            _set(row, 9, self._cat_name.get(t["category_id"], ""))
            _set(row, 10, self._sub_name.get(t["subcategory_id"], ""))
            _set(row, 11, iso_to_br(t["data_lanc"]))
            _set(row, 12, t["tipo"])
            _set(row, 13, t["id"])  # hidden

            self._rows_by_id[int(t["id"])] = dict(t)

        if self.table.rowCount():
            self.table.selectRow(0)
        self._update_status_from_selection()

    # ----------------------------- ações de linha ----------------------------
    def _selected_tx_id(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 13)
        if not it:
            return None
        try:
            return int(it.text())
        except Exception:
            return None

    def edit_selected(self):
        tx_id = self._selected_tx_id()
        if not tx_id:
            return
        row = self.db.q("SELECT * FROM transactions WHERE id=?", (tx_id,))
        if not row:
            return
        t = row[0]
        self.current_tx_id = tx_id

        # tipo
        if t["tipo"] == "PAGAR":
            self.rbPagar.setChecked(True)
        else:
            self.rbReceber.setChecked(True)
        # combos dependentes do tipo
        self._refresh_entities_by_tipo()
        self._refresh_categories_by_tipo()
        self._load_subcategories_for_form()

        # campos
        set_combo_by_data(self.cbEnt, t["entity_id"])
        self.dtLanc.setDate(QDate.fromString(str(t["data_lanc"]), "yyyy-MM-dd"))
        self.dtVenc.setDate(QDate.fromString(str(t["data_venc"]), "yyyy-MM-dd"))
        set_combo_by_data(self.cbCat, t["category_id"])
        self._load_subcategories_for_form()
        set_combo_by_data(self.cbSub, t["subcategory_id"])
        self.edValor.setValue(float(t["valor"] or 0.0))
        if t["forma_pagto"]:
            idx = self.cbForma.findText(t["forma_pagto"])
            if idx < 0:
                self.cbForma.addItem(t["forma_pagto"])
                idx = self.cbForma.findText(t["forma_pagto"])
            self.cbForma.setCurrentIndex(idx)
        self.spParcelas.setValue(int(t["parcelas_qtd"] or 1))
        set_combo_by_data(self.cbBanco, t["banco_id_padrao"])
        self.edDesc.setText(t["descricao"] or "")
        self.btnStatus.setText(t["status"])

    def delete(self):
        tx_id = self._selected_tx_id()
        if not tx_id:
            return
        if not msg_yesno("Excluir este lançamento?"):
            return
        try:
            self.db.transaction_delete(tx_id)
            msg_info("Lançamento excluído.")
            self.current_tx_id = None
            self.apply_filters()
            self.data_changed.emit()
        except sqlite3.IntegrityError as e:
            msg_err(str(e), self)

    def cancel_selected(self):
        tx_id = self._selected_tx_id()
        if not tx_id:
            return
        if not msg_yesno("Cancelar este lançamento?"):
            return
        self.db.e("UPDATE transactions SET status='CANCELADO', updated_at=datetime('now') WHERE id=?", (tx_id,))
        self.apply_filters()
        self.data_changed.emit()

    def liquidar(self):
        tx_id = self._selected_tx_id()
        if not tx_id:
            return
        # carrega dados do tx para passar ao diálogo
        row = self.db.q(
            "SELECT t.*, IFNULL((SELECT SUM(p.amount + p.interest - p.discount) FROM payments p WHERE p.transaction_id=t.id),0) AS pago "
            "FROM transactions t WHERE t.id=?", (tx_id,)
        )
        if not row:
            return
        tx = row[0]
        dlg = PaymentDialog(self.db, self.company_id, tx, self.user_id, self)
        if dlg.exec_() and dlg.ok_clicked:
            # atualiza status se liquidado
            tot = self.db.q(
                "SELECT IFNULL(SUM(amount + interest - discount),0) AS tot FROM payments WHERE transaction_id=?",
                (tx_id,),
            )[0]["tot"]
            if float(tot) >= float(tx["valor"] or 0.0) - 1e-6 and (tx["status"] != "CANCELADO"):
                self.db.e("UPDATE transactions SET status='LIQUIDADO', updated_at=datetime('now') WHERE id=?", (tx_id,))
            self.apply_filters()
            self.data_changed.emit()

    # --------------------------- ações do formulário -------------------------
    def new(self):
        self.current_tx_id = None
        self.rbPagar.setChecked(True)
        self._refresh_entities_by_tipo()
        self._refresh_categories_by_tipo()
        self._load_subcategories_for_form()
        self.cbEnt.setCurrentIndex(0)
        self.dtLanc.setDate(QDate.currentDate())
        self.dtVenc.setDate(QDate.currentDate())
        self.cbCat.setCurrentIndex(0)
        self.cbSub.setCurrentIndex(0)
        self.edValor.setValue(0.0)
        self.cbForma.setCurrentIndex(0)
        self.spParcelas.setValue(1)
        if self.cbBanco.count():
            self.cbBanco.setCurrentIndex(0)
        self.edDesc.clear()
        self.btnStatus.setText("EM ABERTO")

    def save(self):
        tipo = self._current_tipo()
        rec = dict(
            company_id=self.company_id,
            tipo=tipo,
            entity_id=self.cbEnt.currentData(),
            category_id=self.cbCat.currentData(),
            subcategory_id=self.cbSub.currentData(),
            descricao=self.edDesc.toPlainText().strip(),
            data_lanc=qdate_to_iso(self.dtLanc.date()),
            data_venc=qdate_to_iso(self.dtVenc.date()),
            forma_pagto=self.cbForma.currentText(),
            parcelas_qtd=self.spParcelas.value(),
            valor=self.edValor.value(),
            banco_id_padrao=self.cbBanco.currentData(),
            created_by=self.user_id,
        )

        if not rec["category_id"]:
            msg_err("Selecione a categoria.")
            return

        try:
            tx_id = self.db.transaction_save(rec, self.current_tx_id)
            self.current_tx_id = tx_id
            msg_info("Lançamento salvo.")
            self.apply_filters()
            self.data_changed.emit()
        except sqlite3.IntegrityError as e:
            msg_err(str(e), self)

    # --------------------------- reações de UI -------------------------------
    def on_tipo_changed(self):
        # Atualiza combos dependentes do tipo
        self._refresh_entities_by_tipo()
        self._refresh_categories_by_tipo()
        self._load_subcategories_for_form()

    def _update_status_from_selection(self):
        r = self.table.currentRow()
        if r < 0:
            self.btnStatus.setText("EM ABERTO")
            return
        it = self.table.item(r, 0)
        self.btnStatus.setText(it.text() if it else "EM ABERTO")
# ======================== FIM DA NOVA TransactionsDialog ======================

class CashflowDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.setWindowTitle("Fluxo de Caixa")

        # período (agora mais largos para não cortar o ano)
        self.dtIni = QDateEdit(QDate.currentDate().addMonths(-1)); set_br_date(self.dtIni)
        self.dtIni.setMinimumWidth(140)
        self.dtFim = QDateEdit(QDate.currentDate());                set_br_date(self.dtFim)
        self.dtFim.setMinimumWidth(140)

        # seletor de banco
        self.cbBank = QComboBox()
        self.cbBank.addItem("Todos", None)
        for b in self.db.banks(self.company_id):
            self.cbBank.addItem(f"{b['bank_name']} - {b['account_name'] or ''}", b["id"])

        # tabela com as colunas solicitadas
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Valor", "Tipo", "Data da liquidação",
            "Fornecedor/Cliente", "Categoria", "Subcategoria"
        ])
        stretch_table(self.table); zebra_table(self.table)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)

        # total
        self.lbTotal = QLabel("Total: R$ 0,00")

        # botões
        btAtualizar = QPushButton("Atualizar")
        btAtualizar.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btPdf = QPushButton("Exportar PDF");       btPdf.setIcon(std_icon(self, self.style().SP_DriveDVDIcon))
        btCsv = QPushButton("Exportar Excel/CSV"); btCsv.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btPdf.clicked.connect(lambda: export_pdf_from_table(self, self.table, "Fluxo_de_Caixa"))
        btCsv.clicked.connect(lambda: export_excel_from_table(self, self.table, "Fluxo_de_Caixa"))
        btAtualizar.clicked.connect(self.load)
        self.cbBank.currentIndexChanged.connect(self.load)

        # linha superior (período + atualizar + banco)
        form = QHBoxLayout()
        form.addWidget(QLabel("Início:")); form.addWidget(self.dtIni)
        form.addWidget(QLabel("Fim:"));    form.addWidget(self.dtFim)
        form.addWidget(btAtualizar)
        form.addSpacing(8)
        form.addWidget(QLabel("Banco:")); form.addWidget(self.cbBank)
        form.addStretch()

        # layout
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.table)
        lay.addWidget(self.lbTotal)
        hl = QHBoxLayout(); hl.addWidget(btPdf); hl.addWidget(btCsv); hl.addStretch()
        lay.addLayout(hl)

        self.load()
        enable_autosize(self, 0.85, 0.75, 1100, 650)

    def load(self):
        """
        Lista pagamentos (apenas de lançamentos LIQUIDADOS) no período,
        com sinal positivo para RECEBER e negativo para PAGAR.
        Filtro opcional por banco.
        """
        dt_ini = qdate_to_iso(self.dtIni.date())
        dt_fim = qdate_to_iso(self.dtFim.date())
        bank_id = self.cbBank.currentData()

        sql = """
            SELECT
                CASE WHEN t.tipo='RECEBER'
                     THEN (p.amount + p.interest - p.discount)
                     ELSE -(p.amount + p.interest - p.discount)
                END AS valor,
                t.tipo AS tipo,
                p.payment_date AS data_liq,
                IFNULL(e.razao_social,'') AS entidade,
                IFNULL(c.name,'') AS categoria,
                IFNULL(s.name,'') AS subcategoria
            FROM payments p
            JOIN transactions t     ON t.id = p.transaction_id
            LEFT JOIN entities e     ON e.id = t.entity_id
            LEFT JOIN categories c   ON c.id = t.category_id
            LEFT JOIN subcategories s ON s.id = t.subcategory_id
            WHERE p.company_id = ?
              AND date(p.payment_date) BETWEEN date(?) AND date(?)
              AND t.status = 'LIQUIDADO'
        """
        params = [self.company_id, dt_ini, dt_fim]
        if bank_id:
            sql += " AND p.bank_id = ?"
            params.append(bank_id)
        sql += " ORDER BY date(p.payment_date)"

        rows = self.db.q(sql, tuple(params))

        # preenche tabela
        self.table.setRowCount(0)
        total = 0.0
        for r in rows:
            row = self.table.rowCount(); self.table.insertRow(row)
            val = float(r["valor"] or 0.0)
            total += val
            self.table.setItem(row, 0, QTableWidgetItem(fmt_brl(val)))
            self.table.setItem(row, 1, QTableWidgetItem(r["tipo"]))
            self.table.setItem(row, 2, QTableWidgetItem(iso_to_br(r["data_liq"])))
            self.table.setItem(row, 3, QTableWidgetItem(r["entidade"]))
            self.table.setItem(row, 4, QTableWidgetItem(r["categoria"]))
            self.table.setItem(row, 5, QTableWidgetItem(r["subcategoria"]))

        self.lbTotal.setText(f"Total: {fmt_brl(total)}")

# ===== [SUBSTITUA A CLASSE DREDialog INTEIRA POR ESTA] ======================
class DREDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Demonstração de Resultado (DRE)")

        self.spAno=QSpinBox(); self.spAno.setRange(2000,2099); self.spAno.setValue(date.today().year)
        self.spMes=QSpinBox(); self.spMes.setRange(0,12); self.spMes.setValue(0)
        self.cbReg=QComboBox(); self.cbReg.addItems(["COMPETENCIA","CAIXA"])

        btGerar = QPushButton("Gerar"); btGerar.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btGerar.clicked.connect(self.gerar)

        btPdf = QPushButton("Exportar PDF"); btPdf.setIcon(std_icon(self, self.style().SP_DriveDVDIcon))
        btPdf.clicked.connect(self.export_pdf)

        top=QHBoxLayout()
        for w in [QLabel("Ano:"), self.spAno, QLabel("Mês (0=todos):"), self.spMes, QLabel("Regime:"), self.cbReg, btGerar]:
            top.addWidget(w)
        top.addStretch()

        # Visualização (HTML)
        from PyQt5.QtWidgets import QTextEdit
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("QTextEdit{background:#ffffff;border:0;padding:0;}")

        lay=QVBoxLayout(self); lay.addLayout(top); lay.addWidget(self.view)
        hl=QHBoxLayout(); hl.addWidget(btPdf); hl.addStretch(); lay.addLayout(hl)

        enable_autosize(self, 0.85, 0.75, 1100, 650)
        self.gerar()

    # ------- helpers ----------
    def _cab(self, txt):
        # Cabeçalho do bloco: borda completa e centralizado
        return (
            '<tr>'
            '<td colspan="2" '
            'style="background:#ddd;text-align:center;font-weight:700;'
            'padding:6px 4px;border:1px solid #333;border-bottom:2px solid #333;">'
            f'{txt}'
            '</td>'
            '</tr>'
            # Cabeçalho das colunas com larguras fixas
            '<tr>'
            '<td style="width:520px;background:#eee;font-weight:700;'
            'padding:6px 8px;border:1px solid #333;border-bottom:1px solid #bdbdbd;'
            'white-space:nowrap;">CATEGORIA</td>'
            '<td style="width:200px;background:#eee;font-weight:700;'
            'padding:6px 8px;border:1px solid #333;border-bottom:1px solid #bdbdbd;'
            'text-align:right;white-space:nowrap;">VALOR</td>'
            '</tr>'
        )

    def _linha(self, nome, valor, negativo=False, zebra=False):
        vtxt = fmt_brl(abs(valor))
        if negativo and valor != 0:
            vtxt = "-" + vtxt
        bg = "background:#f6f6f6;" if zebra else ""
        td_left  = f'padding:6px 8px;border:1px solid #bdbdbd;{bg}white-space:nowrap;'
        td_right = f'padding:6px 8px;border:1px solid #bdbdbd;{bg}text-align:right;white-space:nowrap;'
        return (
            "<tr>"
            f'<td style="{td_left}">{nome}</td>'
            f'<td style="{td_right}">{vtxt}</td>'
            "</tr>"
        )

    def _style(self):
        # Sem CSS global: tudo inline (Qt respeita melhor)
        return ""

    def gerar(self):
        """
        Monta o HTML do DRE.
        - Abre a <table> com <colgroup> para 2 colunas de largura fixa.
        - 'Margem Líquida' sem colspan (preserva a divisória central) e com bordas.
        """
        ano = self.spAno.value()
        mes = self.spMes.value() or None
        reg = self.cbReg.currentText()

        # Totais por categoria
        rows = self.db.dre(self.company_id, ano, mes, reg)
        rec_rows = [r for r in rows if r["tipo"] == "RECEBER"]
        pag_rows = [
            r for r in rows
            if r["tipo"] == "PAGAR" and (r["categoria"] or "").upper() != "DESPESAS COM IMPOSTOS"
        ]

        # Retenções detalhadas
        ret_map = self.db.dre_retencoes_por_sub(self.company_id, ano, mes, reg)
        total_ret = sum(ret_map.values())

        # ===== HTML =====
        html = ["<!doctype html><html><head>", self._style(), "</head><body>"]

        # Tabela central com 2 colunas
        html.append(
            '<table class="box" cellpadding="0" cellspacing="0">'
            '<colgroup><col><col></colgroup>'
        )

        # --- CONTAS A RECEBER ---
        html.append(self._cab("CONTAS A RECEBER"))
        z = False
        rec_total = 0.0
        for r in rec_rows:
            v = float(r["total"] or 0.0)
            rec_total += v
            html.append(self._linha(r["categoria"], v, negativo=False, zebra=z))
            z = not z

        html.append('<tr class="sep"><td colspan="2"></td></tr>')

        # --- RETENÇÕES DE IMPOSTOS ---
        html.append(self._cab("RETENÇÕES DE IMPOSTOS"))
        z = False
        for nome in ("COFINS", "CSLL", "IRPJ", "PIS"):
            html.append(self._linha(nome, ret_map.get(nome, 0.0), negativo=True, zebra=z))
            z = not z

        html.append('<tr class="sep"><td colspan="2"></td></tr>')

        # --- CONTAS A PAGAR (sem impostos) ---
        html.append(self._cab("CONTAS A PAGAR"))
        z = False
        pag_total = 0.0
        for r in pag_rows:
            v = float(r["total"] or 0.0)
            pag_total += v
            html.append(self._linha(r["categoria"], v, negativo=True, zebra=z))
            z = not z

        # --- MARGEM LÍQUIDA (box com bordas fechadas) ---
        margem = rec_total - total_ret - pag_total
        perc = (margem / rec_total * 100.0) if rec_total else 0.0
        perc_txt = f"{perc:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")

        # separador mantendo laterais
        html.append(
            '<tr>'
            '<td style="height:10px;border-left:1px solid #bdbdbd;border-right:1px solid #bdbdbd;"></td>'
            '<td style="height:10px;border-left:1px solid #bdbdbd;border-right:1px solid #bdbdbd;"></td>'
            '</tr>'
        )

        # cabeçalho do bloco
        html.append(
            '<tr><td colspan="2" '
            'style="background:#ddd;text-align:center;font-weight:700;'
            'padding:6px 4px;border:1px solid #333;border-bottom:2px solid #333;">'
            'MARGEM LÍQUIDA'
            '</td></tr>'
        )

        # linha do valor (sem colspan — mantém a divisória central)
        html.append(
            '<tr>'
            '<td style="padding:6px 8px;border:1px solid #bdbdbd;white-space:nowrap;"></td>'
            f'<td style="padding:6px 8px;border:1px solid #bdbdbd;'
            f'text-align:right;font-weight:700;white-space:nowrap;">{fmt_brl(margem)}</td>'
            '</tr>'
        )

        # linha do percentual (também sem colspan)
        html.append(
            '<tr>'
            '<td style="padding:6px 8px;border:1px solid #bdbdbd;white-space:nowrap;"></td>'
            f'<td style="padding:6px 8px;border:1px solid #bdbdbd;'
            f'text-align:right;white-space:nowrap;">{perc_txt}</td>'
            '</tr>'
        )

        html.append("</table></body></html>")
        self.view.setHtml("".join(html))

    def export_pdf(self):
        # Gera PDF 800x800
        fn,_ = QFileDialog.getSaveFileName(self, "Salvar PDF", "DRE.pdf", "PDF (*.pdf)")
        if not fn:
            return
        if not fn.lower().endswith(".pdf"):
            fn += ".pdf"
        doc_html = self.view.toHtml()
        doc = QTextDocument()
        doc.setHtml(doc_html)
        pr = QPrinter(QPrinter.HighResolution)
        pr.setOutputFormat(QPrinter.PdfFormat)
        pr.setPageSizeMM(QSizeF(211.67, 211.67))  # ~800x800 px a 96 dpi (aprox)
        pr.setOutputFileName(fn)
        doc.print_(pr)
        msg_info(f"PDF gerado em:\n{fn}", self)
# =============================================================================
# NfeDialog
# =============================================================================
class NfeDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.setWindowTitle("Emissão NFS-e (NFE)")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Módulo de NFS-e — em desenvolvimento."))
        bt = QPushButton("Fechar")
        bt.clicked.connect(self.close)
        hl = QHBoxLayout(); hl.addStretch(1); hl.addWidget(bt)
        lay.addLayout(hl)
        enable_autosize(self, 0.4, 0.3, 480, 260)

class EmitirNfeDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db; self.company_id = company_id
        self.setWindowTitle("Emitir NFS-e")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Tela de emissão de NFS-e (placeholder)."))
        bt = QPushButton("Fechar"); bt.clicked.connect(self.close)
        hl = QHBoxLayout(); hl.addStretch(1); hl.addWidget(bt)
        lay.addLayout(hl)
        enable_autosize(self, 0.45, 0.35, 520, 300)

class MonitorXmlDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db; self.company_id = company_id
        self.setWindowTitle("Monitor de XML")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Monitor de XML (placeholder)."))
        btClose = QPushButton("Fechar"); btClose.clicked.connect(self.close)
        hl = QHBoxLayout(); hl.addStretch(1); hl.addWidget(btClose)
        lay.addLayout(hl)
        enable_autosize(self, 0.55, 0.4, 620, 340)
# =============================================================================
# Central NFS-e
# =============================================================================
class NfeCenterDialog(QDialog):
    """
    Janela com dois botões:
      - Emitir NFS-e  (placeholder por enquanto)
      - Monitor de XML (abre automaticamente o 'Monitor NF-e.py' se encontrado)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Emissão NFS-e (NFE)")

        title = QLabel("Central de NFS-e")
        f = title.font(); f.setPointSize(14); f.setBold(True)
        title.setFont(f)

        self.btEmitir  = QPushButton("Emitir NFS-e")
        self.btMonitor = QPushButton("Monitor de XML")

        # ícones padrão
        self.btEmitir.setIcon(std_icon(self, self.style().SP_FileDialogDetailedView))
        self.btMonitor.setIcon(std_icon(self, self.style().SP_ComputerIcon))

        self.btEmitir.clicked.connect(self.open_emitir_nfe)
        self.btMonitor.clicked.connect(self.open_monitor_xml)

        lay = QVBoxLayout(self)
        lay.addWidget(title)
        lay.addSpacing(4)
        lay.addWidget(self.btEmitir)
        lay.addWidget(self.btMonitor)
        lay.addStretch(1)

        # estilo leve + tamanho
        self.setStyleSheet("""
            QPushButton { border: 1px solid #d0d0d0; border-radius: 8px; padding: 8px 12px; background:#f7f7f7; }
            QPushButton:hover { background:#f0f0f0; }
        """)
        enable_autosize(self, 0.35, 0.30, 420, 260)

    # -------------------- ações --------------------
    def open_emitir_nfe(self):
        # Coloque aqui a integração real quando tiver o emissor.
        msg_info("Módulo de emissão ainda não configurado nesta versão.", self)

    def open_monitor_xml(self):
        # Redireciona para o método do MainWindow, que bloqueia o ERP
        parent = self.parent()
        if parent and hasattr(parent, "run_monitor_nfe"):
            self.close()  # opcional: fechar a central
            parent.run_monitor_nfe()
            return
        # Fallback (se aberto isolado, pouco provável)
        msg_err("Abra o Monitor pelo ERP para bloquear a tela corretamente.", self)

    # -------------------- helpers --------------------
    def _find_monitor_script(self) -> Path | None:
        """
        Procura por 'Monitor NF-e.py' (case-insensitive) na pasta do app e subpastas.
        """
        root = Path(__file__).resolve().parent

        # alvos diretos mais comuns
        direct = root / "Monitor NF-e.py"
        subdir  = root / "Monitor NF-e" / "Monitor NF-e.py"
        if direct.exists():
            return direct
        if subdir.exists():
            return subdir

        # busca recursiva case-insensitive
        target = "monitor nf-e.py"
        for p in root.rglob("*.py"):
            if p.name.lower() == target:
                return p
        return None

# =============================================================================
# Login + Main (dashboard)
# =============================================================================
class LoginWindow(QWidget):
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        self.setWindowTitle(f"{APP_TITLE} - Login")

        self.cbEmp = QComboBox()
        self.cbUser = QComboBox()
        self.cbEmp.currentIndexChanged.connect(self.reload_users)

        self.edPass = QLineEdit()
        self.edPass.setEchoMode(QLineEdit.Password)

        self.btEntrar = QPushButton("Entrar")
        self.btEntrar.setIcon(std_icon(self, self.style().SP_DialogOkButton))
        self.btEntrar.clicked.connect(self.login)

        # ⟵ ADICIONE ESTA LINHA
        self.edPass.returnPressed.connect(self.btEntrar.click)

        self.btEmp = QPushButton("Cadastro de empresa")
        self.btEmp.setIcon(std_icon(self, self.style().SP_ComputerIcon))
        self.btUser = QPushButton("Cadastro de usuário")
        self.btUser.setIcon(std_icon(self, self.style().SP_DirHomeIcon))
        self.btEmp.clicked.connect(self.open_emp_admin)
        self.btUser.clicked.connect(self.open_user_admin)

        form = QFormLayout()
        form.addRow("Empresa:", self.cbEmp)
        form.addRow("Usuário:", self.cbUser)
        form.addRow("Senha:", self.edPass)

        hl = QHBoxLayout()
        hl.addWidget(self.btEmp)
        hl.addWidget(self.btUser)
        hl.addStretch()

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.btEntrar)
        lay.addLayout(hl)

        # carrega listas na criação
        self.reload_companies()
        enable_autosize(self, 0.45, 0.4, 520, 360)

    # garante atualização quando a janela volta a aparecer
    def showEvent(self, e):
        super().showEvent(e)
        self.reload_companies()
        self.edPass.setFocus()

    def reload_companies(self, keep_id=None):
        """Recarrega empresas e mantém a atual, se possível."""
        if keep_id is None and self.cbEmp.count():
            keep_id = self.cbEmp.currentData()

        self.cbEmp.blockSignals(True)
        self.cbEmp.clear()
        for c in self.db.list_companies():
            self.cbEmp.addItem(c["razao_social"], c["id"])
        self.cbEmp.blockSignals(False)

        if self.cbEmp.count():
            idx = self.cbEmp.findData(keep_id) if keep_id is not None else 0
            if idx < 0:
                idx = 0
            self.cbEmp.setCurrentIndex(idx)

        self.reload_users()

    def reload_users(self):
        """Carrega usuários da empresa selecionada; se não houver, mostra todos."""
        self.cbUser.clear()
        company_id = self.cbEmp.currentData()
        rows = self.db.list_users_for_company(company_id) if company_id else []
        if not rows:
            # fallback: lista todos os usuários ativos para permitir seleção
            rows = self.db.users_all()
        for u in rows:
            self.cbUser.addItem(f"{u['name']} ({u['username']})", u["username"])

    def open_emp_admin(self):
        auth = AdminAuthDialog(self.db, self)
        if auth.exec_() and auth.ok:
            CompaniesDialog(self.db, self).exec_()
            self.reload_companies(keep_id=self.cbEmp.currentData())

    def open_user_admin(self):
        auth = AdminAuthDialog(self.db, self)
        if auth.exec_() and auth.ok:
            UsersDialog(self.db, self).exec_()
            # recarrega mantendo empresa atual
            self.reload_users()

    def login(self):
        company_id = self.cbEmp.currentData()
        username = self.cbUser.currentData()
        user = self.db.verify_login(company_id, username, self.edPass.text())
        if not user:
            msg_err("Login inválido ou sem acesso à empresa.")
            return
        self.hide()
        self.main = MainWindow(self.db, company_id, user)
        self.main.show()

class MainWindow(QMainWindow):
    def __init__(self, db: DB, company_id: int, user_row: sqlite3.Row):
        super().__init__()
        self.db = db
        self.company_id = company_id
        self.user = user_row

        # Permissões carregadas para o usuário logado
        self.allowed_codes = self.db.allowed_codes(self.user["id"], self.company_id)

        comp = self.db.q("SELECT razao_social FROM companies WHERE id=?", (company_id,))[0]["razao_social"]
        self.setWindowTitle(f"{APP_TITLE} - {comp}")

        menubar = self.menuBar()

        # ===== Cadastros =====
        cad_actions = []
        actBanks = QAction("Bancos", self);                    actBanks.triggered.connect(self.open_banks)
        actEnts  = QAction("Fornecedores/Clientes", self);     actEnts.triggered.connect(self.open_entities)
        actCats  = QAction("Categorias/Subcategorias", self);  actCats.triggered.connect(self.open_categories)

        if self.has("BANCOS"):               cad_actions.append(actBanks)
        if self.has("FORNECEDOR_CLIENTE"):   cad_actions.append(actEnts)
        if self.has("CONTAS"):               cad_actions.append(actCats)

        if self.db.is_admin(self.user["id"]):
            actEmpAdmin  = QAction("Empresas (admin)", self); actEmpAdmin.triggered.connect(self.open_companies_admin)
            actUserAdmin = QAction("Usuários (admin)", self);  actUserAdmin.triggered.connect(self.open_users_admin)
            if cad_actions:
                cad_actions.append(None)
            cad_actions.extend([actEmpAdmin, actUserAdmin])

        if cad_actions:
            mCad = menubar.addMenu("Cadastros")
            for a in cad_actions:
                mCad.addSeparator() if a is None else mCad.addAction(a)

        # ===== Movimentação =====
        mov_actions = []
        actTx = QAction("Lançamentos (Pagar/Receber)", self); actTx.triggered.connect(self.open_transactions)
        if self.has("CONTAS"):
            mov_actions.append(actTx)

        # Botão/ação para Emissão NFS-e (NFE)
        actNfe = QAction("Emissão NFS-e (NFE)", self)
        actNfe.triggered.connect(self.open_nfse_center)
        if self.has("NFE"):
            mov_actions.append(actNfe)

        if mov_actions:
            mMov = menubar.addMenu("Movimentação")
            for a in mov_actions:
                mMov.addAction(a)

        # ===== Relatórios =====
        rel_actions = []
        actFluxo = QAction("Fluxo de Caixa", self); actFluxo.triggered.connect(self.open_cashflow)
        actDre   = QAction("DRE", self);            actDre.triggered.connect(self.open_dre)

        if self.has("CONTAS"): rel_actions.append(actFluxo)
        if self.has("DRE"):    rel_actions.append(actDre)

        if rel_actions:
            mRel = menubar.addMenu("Relatórios")
            for a in rel_actions:
                mRel.addAction(a)

        # ===== Sair =====
        actSair = QAction("Sair", self); actSair.triggered.connect(self.close)
        menubar.addAction(actSair)

        # ================== Dashboard ==================
        w = QWidget(); v = QVBoxLayout(w)

        title_row = QHBoxLayout()
        lbTitle = QLabel("Sistema de Gestão Financeira")
        lbTitle.setStyleSheet("font-size:26px;font-weight:600;")
        lbCompany = QLabel(comp)
        lbCompany.setStyleSheet("font-size:12px;font-style:italic;color:#444;")
        title_row.addWidget(lbTitle); title_row.addStretch(); title_row.addWidget(lbCompany)
        v.addLayout(title_row)

        center = QHBoxLayout()

        # Filtros do período
        left = QVBoxLayout(); left.addStretch(1)
        filter_box = QHBoxLayout()
        self.cbMes = QComboBox()
        self.cbMes.addItems([
            "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
        ])
        self.spAno = QSpinBox(); self.spAno.setRange(2000, 2099); self.spAno.setValue(date.today().year)
        filter_box.addWidget(QLabel("Período:")); filter_box.addWidget(self.cbMes)
        filter_box.addSpacing(12); filter_box.addWidget(QLabel("Ano:")); filter_box.addWidget(self.spAno)
        left.addLayout(filter_box)
        center.addLayout(left, 1)

        # Cartões de totais
        right = QVBoxLayout()
        panel = QGroupBox(""); panel_l = QVBoxLayout(panel)

        grpR = QGroupBox("Contas a Receber"); lr = QVBoxLayout(grpR)
        self.lbReceber = QLabel("R$ 0,00"); self.lbReceber.setAlignment(Qt.AlignCenter)
        self.lbReceber.setStyleSheet(
            "QLabel{font-size:28px;font-weight:700;color:#0a8f3c;"
            "border:1px solid #999;border-radius:10px;padding:12px;background:#fff;}"
        )
        lr.addWidget(self.lbReceber)

        grpP = QGroupBox("Contas a Pagar"); lp = QVBoxLayout(grpP)
        self.lbPagar = QLabel("-R$ 0,00"); self.lbPagar.setAlignment(Qt.AlignCenter)
        self.lbPagar.setStyleSheet(
            "QLabel{font-size:28px;font-weight:700;color:#b32020;"
            "border:1px solid #999;border-radius:10px;padding:12px;background:#fff;}"
        )
        lp.addWidget(self.lbPagar)

        panel_l.addWidget(grpR); panel_l.addWidget(grpP)
        right.addWidget(panel, 3)
        center.addLayout(right, 2)

        v.addLayout(center)
        self.setCentralWidget(w)

        self.cbMes.currentIndexChanged.connect(self.update_dashboard)
        self.spAno.valueChanged.connect(self.update_dashboard)
        self.cbMes.setCurrentIndex(date.today().month - 1)
        self.update_dashboard()

        enable_autosize(self, 0.95, 0.9, 1280, 740)

    # ---------- Helpers de permissão ----------
    # --- permissões util ---
    def has(self, code: str) -> bool:
        return code in self.allowed_codes

    # --- Cadastros ---
    def open_banks(self):
        if not self.has("BANCOS"):
            msg_err("Você não tem permissão para Bancos.", self)
            return
        BanksDialog(self.db, self.company_id, self).exec_()

    def open_entities(self):
        if not self.has("FORNECEDOR_CLIENTE"):
            msg_err("Você não tem permissão para Fornecedores/Clientes.", self)
            return
        EntitiesDialog(self.db, self.company_id, self).exec_()

    def open_categories(self):
        if not self.has("CONTAS"):
            msg_err("Você não tem permissão para Categorias/Subcategorias.", self)
            return
        CategoriesDialog(self.db, self.company_id, self).exec_()

    # --- Movimentação ---
    def open_transactions(self):
        if not self.has("CONTAS"):
            msg_err("Você não tem permissão para Lançamentos.", self)
            return
        dlg = TransactionsDialog(self.db, self.company_id, self.user["id"], self)
        dlg.data_changed.connect(self.update_dashboard)
        dlg.exec_()

    def open_cashflow(self):
        if not self.has("CONTAS"):
            msg_err("Você não tem permissão para Fluxo de Caixa.", self)
            return
        CashflowDialog(self.db, self.company_id, self).exec_()

    def open_dre(self):
        if not self.has("DRE"):
            msg_err("Você não tem permissão para DRE.", self)
            return
        DREDialog(self.db, self.company_id, self).exec_()

    def open_nfse_center(self):
        if not self.has("NFE"):
            msg_err("Você não tem permissão para Emissão NFS-e.", self)
            return
        NfeCenterDialog(self).exec_()

    def open_companies_admin(self):
        if not self.db.is_admin(self.user["id"]):
            msg_err("Apenas administradores podem abrir o cadastro de empresas.", self)
            return
        CompaniesDialog(self.db, self).exec_()

    def open_users_admin(self):
        if not self.db.is_admin(self.user["id"]):
            msg_err("Apenas administradores podem abrir o cadastro de usuários.", self)
            return
        UsersDialog(self.db, self).exec_()

    # ----------- Monitor NF-e (bloqueia ERP enquanto roda) -----------
    def run_monitor_nfe(self):
        script = self._find_monitor_script()
        if not script:
            msg_err("Não encontrei o arquivo 'Monitor NF-e.py'. Coloque-o na pasta do ERP (ou subpasta 'Monitor NF-e').", self)
            return

        # Janela modal simples enquanto o processo roda
        wait = QDialog(self)
        wait.setWindowTitle("Monitor NF-e")
        v = QVBoxLayout(wait)
        v.addWidget(QLabel(f"Executando: {script.name}\nAguarde o término do processo..."))
        btn = QPushButton("Cancelar")
        v.addWidget(btn)
        wait.setModal(True)

        proc = QProcess(wait)

        def on_finished(*_):
            wait.accept()

        def on_cancel():
            try:
                proc.kill()
            except Exception:
                pass
            wait.reject()

        proc.finished.connect(on_finished)
        btn.clicked.connect(on_cancel)

        # Inicia
        proc.start(sys.executable, [str(script)])
        if not proc.waitForStarted(4000):
            msg_err("Falha ao iniciar o Monitor NF-e.", self)
            return

        wait.exec_()  # bloqueia até finalizar/cancelar

    def _find_monitor_script(self) -> Path | None:
        root = Path(__file__).resolve().parent
        direct = root / "Monitor NF-e.py"
        subdir = root / "Monitor NF-e" / "Monitor NF-e.py"
        if direct.exists():
            return direct
        if subdir.exists():
            return subdir
        target = "monitor nf-e.py"
        for p in root.rglob("*.py"):
            if p.name.lower() == target:
                return p
        return None

    # ---------------------- Dashboard ----------------------
    def update_dashboard(self):
        # período escolhido
        mes = self.cbMes.currentIndex() + 1  # 1..12
        ano = int(self.spAno.value())

        # dt_ini = 1º dia do mês
        dt_ini = f"{ano:04d}-{mes:02d}-01"
        # dt_fim_excl = 1º dia do mês seguinte
        next_m = 1 if mes == 12 else mes + 1
        next_y = ano + 1 if mes == 12 else ano
        dt_fim_excl = f"{next_y:04d}-{next_m:02d}-01"

        resumo = self.db.resumo_periodo(self.company_id, dt_ini, dt_fim_excl)
        receber = float(resumo.get("RECEBER", 0.0))
        pagar = float(resumo.get("PAGAR", 0.0))

        self.lbReceber.setText(fmt_brl(receber))
        self.lbPagar.setText("-" + fmt_brl(pagar) if pagar else fmt_brl(0.0))

# =============================================================================
def main():
    conn=ensure_db(); db=DB(conn)
    app=QApplication(sys.argv)
    login=LoginWindow(db); login.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    conn = ensure_db()
    db = DB(conn)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    w = LoginWindow(db)
    w.show()
    sys.exit(app.exec_())
