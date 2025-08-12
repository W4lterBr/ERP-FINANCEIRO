# app_erp.py
# =============================================================================
# ERP Financeiro - PyQt5 (completo)
# =============================================================================

import os
import sys
import csv
import sqlite3
import hashlib
from pathlib import Path
from datetime import date

try:
    from hmac import compare_digest as secure_eq
except Exception:
    from secrets import compare_digest as secure_eq

from PyQt5.QtCore import Qt, QDate, QRegExp, QPoint, QSizeF, pyqtSignal
from PyQt5.QtGui import QRegExpValidator, QTextDocument
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QComboBox, QLineEdit, QPushButton, QHBoxLayout,
    QVBoxLayout, QFormLayout, QMessageBox, QMainWindow, QAction, QDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QSpinBox, QDateEdit, QRadioButton,
    QFileDialog, QStyledItemDelegate, QAbstractScrollArea, QAbstractItemView, QMenu,
    QListWidget, QListWidgetItem, QCheckBox, QTextEdit
)
from PyQt5.QtPrintSupport import QPrinter

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
# Delegates
# =============================================================================
class MaskDelegate(QStyledItemDelegate):
    def __init__(self, mask: str = None, regex: str = None, uppercase: bool = False, parent=None):
        super().__init__(parent); self.mask=mask; self.regex=regex; self.uppercase=uppercase
    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        if self.mask: ed.setInputMask(self.mask)
        if self.regex: ed.setValidator(QRegExpValidator(QRegExp(self.regex), ed))
        return ed
    def setEditorData(self, editor, index): editor.setText(index.data() or "")
    def setModelData(self, editor, model, index):
        text = editor.text().upper() if self.uppercase else editor.text()
        model.setData(index, text)

class DocNumberDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setValidator(QRegExpValidator(QRegExp(r"[0-9\.\-\/]*"), ed))
        return ed
    def setEditorData(self, editor, index): editor.setText(index.data() or "")
    def setModelData(self, editor, model, index):
        text = editor.text(); d = only_digits(text)
        if len(d)==11: text = format_cpf(d)
        elif len(d)==14: text = format_cnpj(d)
        model.setData(index, text)

class KindComboDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(["FORNECEDOR", "CLIENTE"])
        return cb
    def setEditorData(self, editor, index):
        val = (index.data() or "").upper()
        if val not in ("FORNECEDOR", "CLIENTE"):
            val = "FORNECEDOR"
        editor.setCurrentText(val)
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
            conn.execute("INSERT OR REPLACE INTO user_permissions(user_id, perm_id, allowed) VALUES(?,?,1)",
                         (admin_id, pid))
        conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('schema_version','1')")
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn

# =============================================================================
# Dados
# =============================================================================
class DB:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn; self.conn.row_factory = sqlite3.Row
    def q(self, sql, params=()): return self.conn.execute(sql, params).fetchall()
    def e(self, sql, params=()):
        cur = self.conn.execute(sql, params); self.conn.commit(); return cur.lastrowid

    # Login/ACL
    def list_companies(self):
        return self.q("SELECT id, razao_social FROM companies WHERE active=1 ORDER BY razao_social")
    def list_users_for_company(self, company_id):
        sql = """SELECT u.id,u.name,u.username FROM users u
                 JOIN user_company_access a ON a.user_id=u.id
                 WHERE a.company_id=? AND u.active=1 ORDER BY u.name"""
        return self.q(sql, (company_id,))
    def verify_login(self, company_id, username, password):
        r = self.q("SELECT * FROM users WHERE username=? AND active=1", (username,))
        if not r: return None
        u = r[0]
        calc = pbkdf2_hash(password, u["password_salt"], u["iterations"])
        if not secure_eq(calc, u["password_hash"]): return None
        ok = self.q("SELECT 1 FROM user_company_access WHERE user_id=? AND company_id=?", (u["id"], company_id))
        if not ok: return None
        return u
    def is_admin(self, user_id):
        r = self.q("SELECT is_admin FROM users WHERE id=?", (user_id,))
        return bool(r and r[0]["is_admin"])

    def allowed_codes(self, user_id: int, company_id: int) -> set:
        """Retorna o conjunto de códigos de permissão do usuário.
        Hoje global por usuário; pronto para evoluir por empresa."""
        if self.is_admin(user_id):
            return {r["code"] for r in self.q("SELECT code FROM permission_types")}
        rows = self.q("""
            SELECT pt.code
              FROM permission_types pt
              JOIN user_permissions up ON up.perm_id = pt.id
             WHERE up.user_id = ? AND up.allowed = 1
        """, (user_id,))
        return {r["code"] for r in rows}

    # Companies
    def companies_all(self): return self.q("SELECT * FROM companies ORDER BY razao_social")
    def company_save(self, rec, company_id=None):
        if company_id:
            self.e("""UPDATE companies SET cnpj=?, razao_social=?, contato1=?, contato2=?, rua=?, bairro=?, numero=?, cep=?, uf=?, cidade=?, email=?, active=?
                      WHERE id=?""",
                   (rec["cnpj"], rec["razao_social"], rec["contato1"], rec["contato2"], rec["rua"], rec["bairro"], rec["numero"],
                    rec["cep"], rec["uf"], rec["cidade"], rec["email"], int(rec["active"]), company_id))
            return company_id
        return self.e("""INSERT INTO companies(cnpj,razao_social,contato1,contato2,rua,bairro,numero,cep,uf,cidade,email,active)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (rec["cnpj"], rec["razao_social"], rec["contato1"], rec["contato2"], rec["rua"], rec["bairro"], rec["numero"],
                        rec["cep"], rec["uf"], rec["cidade"], rec["email"], int(rec["active"])))
    def company_delete(self, company_id): self.e("DELETE FROM companies WHERE id=?", (company_id,))

    # Users
    def users_all(self): return self.q("SELECT * FROM users ORDER BY name")
    def user_save(self, rec, user_id=None):
        if user_id:
            self.e("""UPDATE users SET name=?, username=?, is_admin=?, active=? WHERE id=?""",
                   (rec["name"], rec["username"], int(rec["is_admin"]), int(rec["active"]), user_id))
            return user_id
        salt = os.urandom(16); iters = 240_000
        pw_hash = pbkdf2_hash(rec.get("password", "123456"), salt, iters)
        return self.e("""INSERT INTO users(name, username, password_salt, password_hash, iterations, is_admin, active)
                         VALUES(?,?,?,?,?,?,?)""",
                       (rec["name"], rec["username"], salt, pw_hash, iters, int(rec["is_admin"]), int(rec["active"])))
    def user_delete(self, user_id): self.e("DELETE FROM users WHERE id=?", (user_id,))
    def user_set_password(self, user_id, password):
        salt=os.urandom(16); iters=240_000; pw_hash=pbkdf2_hash(password, salt, iters)
        self.e("UPDATE users SET password_salt=?, password_hash=?, iterations=? WHERE id=?", (salt,pw_hash,iters,user_id))

    def permissions_all(self): return self.q("SELECT * FROM permission_types ORDER BY id")
    def user_perm_map(self, user_id):
        rows=self.q("SELECT perm_id, allowed FROM user_permissions WHERE user_id=?", (user_id,))
        return {r["perm_id"]: bool(r["allowed"]) for r in rows}
    def set_user_permissions(self, user_id, allowed_perm_ids):
        self.e("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
        for (pid,) in self.q("SELECT id FROM permission_types"):
            allow = 1 if pid in allowed_perm_ids else 0
            self.e("INSERT INTO user_permissions(user_id,perm_id,allowed) VALUES(?,?,?)", (user_id, pid, allow))

    def company_access_map(self, user_id):
        rows=self.q("SELECT company_id FROM user_company_access WHERE user_id=?", (user_id,))
        return {r["company_id"] for r in rows}
    def set_company_access(self, user_id, company_ids):
        self.e("DELETE FROM user_company_access WHERE user_id=?", (user_id,))
        for cid in company_ids:
            self.e("INSERT INTO user_company_access(user_id, company_id) VALUES(?,?)", (user_id, cid))

    # Banks
    def banks(self, company_id): return self.q("SELECT * FROM bank_accounts WHERE company_id=? ORDER BY bank_name, account_name", (company_id,))
    def bank_save(self, company_id, rec, bank_id=None):
        if bank_id:
            self.e("""UPDATE bank_accounts SET bank_name=?, account_name=?, account_type=?, agency=?, account_number=?,
                      initial_balance=?, current_balance=?, active=? WHERE id=?""",
                   (rec["bank_name"], rec["account_name"], rec["account_type"], rec["agency"], rec["account_number"],
                    float(rec["initial_balance"]), float(rec["current_balance"]), int(rec["active"]), bank_id))
            return bank_id
        return self.e("""INSERT INTO bank_accounts(company_id,bank_name,account_name,account_type,agency,account_number,
                                                   initial_balance,current_balance,active)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                       (company_id, rec["bank_name"], rec["account_name"], rec["account_type"], rec["agency"], rec["account_number"],
                        float(rec["initial_balance"]), float(rec["current_balance"]), int(rec["active"])))
    def bank_delete(self, bank_id): self.e("DELETE FROM bank_accounts WHERE id=?", (bank_id,))

    # Entities
    def entities(self, company_id, kind=None):
        if kind:
            return self.q("SELECT * FROM entities WHERE company_id=? AND (kind=? OR kind='AMBOS') ORDER BY razao_social", (company_id, kind))
        return self.q("SELECT * FROM entities WHERE company_id=? ORDER BY razao_social", (company_id,))
    def entity_save(self, company_id, rec, entity_id=None):
        if entity_id:
            self.e("""UPDATE entities SET kind=?, cnpj_cpf=?, razao_social=?, contato1=?, contato2=?, rua=?, bairro=?, numero=?, cep=?, uf=?, cidade=?, email=?, active=?
                      WHERE id=?""",
                   (rec["kind"], rec["cnpj_cpf"], rec["razao_social"], rec["contato1"], rec["contato2"], rec["rua"], rec["bairro"],
                    rec["numero"], rec["cep"], rec["uf"], rec["cidade"], rec["email"], int(rec["active"]), entity_id))
            return entity_id
        return self.e("""INSERT INTO entities(company_id,kind,cnpj_cpf,razao_social,contato1,contato2,rua,bairro,numero,cep,uf,cidade,email,active)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (company_id, rec["kind"], rec["cnpj_cpf"], rec["razao_social"], rec["contato1"], rec["contato2"],
                        rec["rua"], rec["bairro"], rec["numero"], rec["cep"], rec["uf"], rec["cidade"], rec["email"], int(rec["active"])))
    def entity_delete(self, entity_id): self.e("DELETE FROM entities WHERE id=?", (entity_id,))

    # Categories/Subcategories
    def categories(self, company_id, tipo=None):
        if tipo:
            return self.q("SELECT * FROM categories WHERE company_id=? AND tipo=? ORDER BY name", (company_id, tipo))
        return self.q("SELECT * FROM categories WHERE company_id=? ORDER BY tipo, name", (company_id,))
    def category_save(self, company_id, name, tipo, cat_id=None):
        if cat_id:
            self.e("UPDATE categories SET name=?, tipo=? WHERE id=?", (name, tipo, cat_id)); return cat_id
        return self.e("INSERT INTO categories(company_id,name,tipo) VALUES(?,?,?)", (company_id, name, tipo))
    def category_delete(self, cat_id): self.e("DELETE FROM categories WHERE id=?", (cat_id,))
    def subcategories(self, category_id): return self.q("SELECT * FROM subcategories WHERE category_id=? ORDER BY name", (category_id,))
    def subcategory_save(self, category_id, name, sub_id=None):
        if sub_id:
            self.e("UPDATE subcategories SET name=?, category_id=? WHERE id=?", (name, category_id, sub_id)); return sub_id
        return self.e("INSERT INTO subcategories(category_id,name) VALUES(?,?)", (category_id, name))
    def subcategory_delete(self, sub_id): self.e("DELETE FROM subcategories WHERE id=?", (sub_id,))

    # Transactions & Payments
    def transactions(self, company_id, tipo=None):
        base = """SELECT t.*, IFNULL((SELECT SUM(p.amount+p.interest-p.discount) FROM payments p WHERE p.transaction_id=t.id),0) AS pago
                  FROM transactions t WHERE t.company_id=?"""
        params=[company_id]
        if tipo: base += " AND t.tipo=?"; params.append(tipo)
        base += " ORDER BY date(data_venc)"
        return self.q(base, tuple(params))
    def transaction_save(self, rec, tx_id=None):
        if tx_id:
            sql = """UPDATE transactions SET tipo=?, entity_id=?, category_id=?, subcategory_id=?, descricao=?, data_lanc=?, data_venc=?,
                     forma_pagto=?, parcelas_qtd=?, valor=?, banco_id_padrao=?, updated_at=datetime('now') WHERE id=?"""
            self.e(sql, (rec["tipo"], rec["entity_id"], rec["category_id"], rec["subcategory_id"], rec["descricao"],
                         rec["data_lanc"], rec["data_venc"], rec["forma_pagto"], int(rec["parcelas_qtd"]),
                         float(rec["valor"]), rec["banco_id_padrao"], tx_id))
            return tx_id
        sql = """INSERT INTO transactions(company_id,tipo,entity_id,category_id,subcategory_id,descricao,data_lanc,data_venc,
                                          forma_pagto,parcelas_qtd,valor,status,banco_id_padrao,created_by)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,'EM_ABERTO',?,?)"""
        return self.e(sql, (rec["company_id"], rec["tipo"], rec["entity_id"], rec["category_id"], rec["subcategory_id"],
                            rec["descricao"], rec["data_lanc"], rec["data_venc"], rec["forma_pagto"],
                            int(rec["parcelas_qtd"]), float(rec["valor"]), rec["banco_id_padrao"], rec["created_by"]))
    def transaction_delete(self, tx_id): self.e("DELETE FROM transactions WHERE id=?", (tx_id,))
    def payments_for(self, tx_id):
        sql = """SELECT p.*, b.bank_name||' - '||IFNULL(b.account_name,'') AS banco
                 FROM payments p JOIN bank_accounts b ON b.id=p.bank_id
                 WHERE p.transaction_id=? ORDER BY date(p.payment_date)"""
        return self.q(sql, (tx_id,))
    def payment_add(self, rec):
        sql = """INSERT INTO payments(transaction_id,company_id,payment_date,bank_id,amount,interest,discount,doc_ref,created_by)
                 VALUES(?,?,?,?,?,?,?,?,?)"""
        return self.e(sql, (rec["transaction_id"], rec["company_id"], rec["payment_date"], rec["bank_id"],
                            float(rec["amount"]), float(rec["interest"]), float(rec["discount"]),
                            rec["doc_ref"], rec["created_by"]))
    def payment_delete(self, payment_id): self.e("DELETE FROM payments WHERE id=?", (payment_id,))

    # DRE / dashboard
    def dre(self, company_id, ano, mes=None, regime='COMPETENCIA'):
        src = "vw_dre_competencia" if regime == 'COMPETENCIA' else "vw_dre_caixa"
        params=[company_id, str(ano)]; filt=""
        if mes: filt=" AND mes=? "; params.append(f"{int(mes):02d}")
        sql=f"""SELECT c.name AS categoria, v.tipo, v.total
                FROM {src} v JOIN categories c ON c.id=v.category_id
                WHERE v.company_id=? AND v.ano=? {filt}
                ORDER BY v.tipo, c.name"""
        return self.q(sql, tuple(params))
    def resumo_periodo(self, company_id, dt_ini: str, dt_fim_excl: str):
        sql = """
            SELECT t.tipo, ROUND(SUM(t.valor - IFNULL((SELECT SUM(p.amount+p.interest-p.discount)
                        FROM payments p WHERE p.transaction_id=t.id),0)),2) AS saldo
            FROM transactions t
            WHERE t.company_id=? AND date(t.data_venc)>=date(?) AND date(t.data_venc)<date(?)
              AND t.status <> 'CANCELADO'
            GROUP BY t.tipo
        """
        rows = self.q(sql, (company_id, dt_ini, dt_fim_excl))
        res = {'PAGAR': 0.0, 'RECEBER': 0.0}
        for r in rows: res[r['tipo']] = max(0.0, float(r['saldo'] or 0))
        return res

# =============================================================================
# Exportações
# =============================================================================
def table_to_html(table: QTableWidget, title: str) -> str:
    head = "<tr>" + "".join(f"<th>{table.horizontalHeaderItem(c).text()}</th>" for c in range(table.columnCount())) + "</tr>"
    rows = []
    for r in range(table.rowCount()):
        tds = []
        for c in range(table.columnCount()):
            it = table.item(r,c)
            tds.append(f"<td>{'' if it is None else it.text()}</td>")
        rows.append("<tr>"+"".join(tds)+"</tr>")
    style = """
    <style>body{font-family:Arial,Helvetica,sans-serif;font-size:12px}
    table{border-collapse:collapse;width:100%}
    th,td{border:1px solid #888;padding:4px 6px}th{background:#eee}</style>
    """
    return f"<!doctype html><html><head>{style}</head><body><h2>{title}</h2><table>{head}{''.join(rows)}</table></body></html>"

def export_pdf_from_table(parent, table: QTableWidget, title: str):
    fn,_ = QFileDialog.getSaveFileName(parent,"Salvar PDF",f"{title}.pdf","PDF (*.pdf)")
    if not fn: return
    html = table_to_html(table, title)
    doc = QTextDocument(); doc.setHtml(html)
    pr = QPrinter(QPrinter.HighResolution); pr.setOutputFormat(QPrinter.PdfFormat)
    if not fn.lower().endswith(".pdf"): fn += ".pdf"
    pr.setOutputFileName(fn); doc.print_(pr)
    msg_info(f"PDF gerado em:\n{fn}", parent)

def export_excel_from_table(parent, table: QTableWidget, title: str):
    try:
        import xlsxwriter
        fn,_ = QFileDialog.getSaveFileName(parent,"Salvar Excel",f"{title}.xlsx","Excel (*.xlsx)")
        if not fn: return
        if not fn.lower().endswith(".xlsx"): fn += ".xlsx"
        wb = xlsxwriter.Workbook(fn); ws = wb.add_worksheet("Dados")
        for c in range(table.columnCount()): ws.write(0,c,table.horizontalHeaderItem(c).text())
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                it = table.item(r,c); ws.write(r+1,c,"" if it is None else it.text())
        wb.close(); msg_info(f"Planilha Excel gerada em:\n{fn}", parent)
    except Exception:
        fn,_ = QFileDialog.getSaveFileName(parent,"Salvar CSV",f"{title}.csv","CSV (*.csv)")
        if not fn: return
        if not fn.lower().endswith(".csv"): fn += ".csv"
        with open(fn,"w",newline="",encoding="utf-8") as f:
            wr=csv.writer(f, delimiter=';')
            wr.writerow([table.horizontalHeaderItem(c).text() for c in range(table.columnCount())])
            for r in range(table.rowCount()):
                wr.writerow([(table.item(r,c).text() if table.item(r,c) else "") for c in range(table.columnCount())])
        msg_info(f"CSV gerado em:\n{fn}", parent)
    
# ===== [ADICIONE JUNTO DAS FUNÇÕES DE EXPORTAÇÃO] ============================
def export_pdf_from_html(parent, html: str, title: str):
    """Gera PDF quadrado (800x800) e usa quase toda a largura para o conteúdo."""
    fn, _ = QFileDialog.getSaveFileName(parent, "Salvar PDF", f"{title}.pdf", "PDF (*.pdf)")
    if not fn:
        return
    if not fn.lower().endswith(".pdf"):
        fn += ".pdf"

    pr = QPrinter(QPrinter.HighResolution)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(fn)

    # Página quadrada 800 x 800 (pontos = px a 72dpi)
    pr.setPaperSize(QSizeF(800, 800), QPrinter.Point)
    pr.setFullPage(True)
    # margens pequenas
    pr.setPageMargins(10, 10, 10, 10, QPrinter.Point)

    # largura útil = 800 - 2*10 = 780; vamos reservar um respiro para a borda da tabela
    doc = QTextDocument()
    doc.setPageSize(QSizeF(780, 780))
    doc.setHtml(html)
    doc.print_(pr)

    msg_info(f"PDF gerado em:\n{fn}", parent)

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
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Cadastro de Bancos / Contas")
        self.table=QTableWidget(0,10)
        self.table.setHorizontalHeaderLabels(["ID","Banco","Nome da Conta","Tipo","Agência","Conta","Saldo Inicial","Saldo Atual","Ativo","Criado em"])
        stretch_table(self.table); zebra_table(self.table)
        self.table.setColumnHidden(0, True)
        btAdd=QPushButton("Novo"); btSave=QPushButton("Salvar"); btDel=QPushButton("Excluir"); btReload=QPushButton("Recarregar")
        for b,ic in ((btAdd,self.style().SP_FileDialogNewFolder),(btSave,self.style().SP_DialogSaveButton),
                     (btDel,self.style().SP_TrashIcon),(btReload,self.style().SP_BrowserReload)):
            b.setIcon(std_icon(self, ic))
        btAdd.clicked.connect(self.add); btSave.clicked.connect(self.save); btDel.clicked.connect(self.delete); btReload.clicked.connect(self.load)
        lay=QVBoxLayout(self); lay.addWidget(self.table); hl=QHBoxLayout(); [hl.addWidget(b) for b in (btAdd,btSave,btDel,btReload)]; lay.addLayout(hl)
        self.load(); enable_autosize(self, 0.7, 0.55, 900, 520)
    def load(self):
        rows=self.db.banks(self.company_id); self.table.setRowCount(0)
        for r in rows:
            row=self.table.rowCount(); self.table.insertRow(row)
            data=[r["id"], r["bank_name"], r["account_name"], r["account_type"], r["agency"], r["account_number"],
                  fmt_brl(r["initial_balance"]), fmt_brl(r["current_balance"]), r["active"], iso_to_br(str(r["created_at"])[:10])]
            for c,val in enumerate(data):
                it=QTableWidgetItem("" if val is None else str(val))
                if c in (0,9): it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row,c,it)
    def add(self):
        r=self.table.rowCount(); self.table.insertRow(r); self.table.setItem(r,0,QTableWidgetItem(""))
        self.table.setItem(r,8,QTableWidgetItem("1"))
    def save(self):
        for r in range(self.table.rowCount()):
            id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
            rec=dict(
                bank_name=self.table.item(r,1).text() if self.table.item(r,1) else "",
                account_name=self.table.item(r,2).text() if self.table.item(r,2) else "",
                account_type=self.table.item(r,3).text() if self.table.item(r,3) else "",
                agency=self.table.item(r,4).text() if self.table.item(r,4) else "",
                account_number=self.table.item(r,5).text() if self.table.item(r,5) else "",
                initial_balance=parse_brl(self.table.item(r,6).text() if self.table.item(r,6) else "0"),
                current_balance=parse_brl(self.table.item(r,7).text() if self.table.item(r,7) else "0"),
                active=1 if (self.table.item(r,8) and self.table.item(r,8).text() not in ("0","False","false")) else 0
            )
            bid=int(id_txt) if id_txt.strip().isdigit() else None
            bid=self.db.bank_save(self.company_id, rec, bid)
            self.table.setItem(r,0,QTableWidgetItem(str(bid)))
        msg_info("Bancos salvos."); self.load()
    def delete(self):
        r=self.table.currentRow()
        if r<0: return
        id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
        if not id_txt.strip().isdigit(): self.table.removeRow(r); return
        if not msg_yesno("Excluir esta conta bancária?"): return
        try: self.db.bank_delete(int(id_txt))
        except sqlite3.IntegrityError as e: msg_err(f"Não foi possível excluir. Conta vinculada a pagamentos.\n{e}"); return
        self.load()

class EntitiesDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Cadastro de Fornecedor / Cliente")
        self.table=QTableWidget(0,13)
        self.table.setHorizontalHeaderLabels(["ID","Tipo","CNPJ/CPF","Razão/Nome","Contato1","Contato2","Rua","Bairro","Nº","CEP","UF","Cidade","Email"])
        stretch_table(self.table); zebra_table(self.table)
        self.table.setColumnHidden(0, True)
        self.table.setItemDelegateForColumn(1, KindComboDelegate(self))
        self.table.setItemDelegateForColumn(2, DocNumberDelegate(self))
        self.table.setItemDelegateForColumn(9, MaskDelegate(mask="00000-000", parent=self))
        self.table.setItemDelegateForColumn(10, MaskDelegate(regex=r"[A-Za-z]{0,2}", uppercase=True, parent=self))
        btAdd=QPushButton("Novo"); btSave=QPushButton("Salvar"); btDel=QPushButton("Excluir"); btReload=QPushButton("Recarregar")
        for b,ic in ((btAdd,self.style().SP_FileDialogNewFolder),(btSave,self.style().SP_DialogSaveButton),
                     (btDel,self.style().SP_TrashIcon),(btReload,self.style().SP_BrowserReload)):
            b.setIcon(std_icon(self, ic))
        btAdd.clicked.connect(self.add); btSave.clicked.connect(self.save); btDel.clicked.connect(self.delete); btReload.clicked.connect(self.load)
        lay=QVBoxLayout(self); lay.addWidget(self.table); hl=QHBoxLayout(); [hl.addWidget(b) for b in (btAdd,btSave,btDel,btReload)]; lay.addLayout(hl)
        self.load(); enable_autosize(self, 0.85, 0.75, 1100, 650)
    def load(self):
        rows = self.db.entities(self.company_id); self.table.setRowCount(0)
        for r in rows:
            row=self.table.rowCount(); self.table.insertRow(row)
            doc = r["cnpj_cpf"] or ""; d=only_digits(doc)
            if len(d)==11: doc=format_cpf(d)
            elif len(d)==14: doc=format_cnpj(d)
            cep = r["cep"] or ""
            if cep:
                dcep=only_digits(cep); cep=f"{dcep[:5]}-{dcep[5:]}" if len(dcep)==8 else cep
            data=[r["id"], r["kind"], doc, r["razao_social"], r["contato1"], r["contato2"], r["rua"], r["bairro"],
                  r["numero"], cep, (r["uf"] or ""), r["cidade"], r["email"]]
            for c,val in enumerate(data):
                it=QTableWidgetItem("" if val is None else str(val))
                if c==0: it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row,c,it)
    def add(self):
        r=self.table.rowCount(); self.table.insertRow(r); self.table.setItem(r,0,QTableWidgetItem("")); self.table.setItem(r,1,QTableWidgetItem("FORNECEDOR"))
    def save(self):
        for r in range(self.table.rowCount()):
            id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
            kind=(self.table.item(r,1).text() if self.table.item(r,1) else "FORNECEDOR").upper()
            if kind not in ("FORNECEDOR","CLIENTE"): kind="FORNECEDOR"
            doc=self.table.item(r,2).text() if self.table.item(r,2) else ""
            d=only_digits(doc)
            if d:
                if len(d)==11 and not validate_cpf(d): msg_err(f"CPF inválido (linha {r+1})."); return
                if len(d)==14 and not validate_cnpj(d): msg_err(f"CNPJ inválido (linha {r+1})."); return
                if len(d) not in (11,14): msg_err(f"Documento deve ter 11 (CPF) ou 14 (CNPJ) dígitos (linha {r+1})."); return
            cep=self.table.item(r,9).text() if self.table.item(r,9) else ""
            uf=self.table.item(r,10).text().upper() if self.table.item(r,10) else ""
            if cep and not validate_cep(cep): msg_err(f"CEP inválido (linha {r+1})."); return
            if uf and not validate_uf(uf): msg_err(f"UF inválida (linha {r+1})."); return
            rec=dict(kind=kind, cnpj_cpf=d, razao_social=self.table.item(r,3).text() if self.table.item(r,3) else "",
                     contato1=self.table.item(r,4).text() if self.table.item(r,4) else "", contato2=self.table.item(r,5).text() if self.table.item(r,5) else "",
                     rua=self.table.item(r,6).text() if self.table.item(r,6) else "", bairro=self.table.item(r,7).text() if self.table.item(r,7) else "",
                     numero=self.table.item(r,8).text() if self.table.item(r,8) else "", cep=only_digits(cep), uf=uf,
                     cidade=self.table.item(r,11).text() if self.table.item(r,11) else "", email=self.table.item(r,12).text() if self.table.item(r,12) else "",
                     active=1)
            if not rec["razao_social"]: msg_err("Razão/Nome é obrigatório."); return
            eid=int(id_txt) if id_txt.strip().isdigit() else None
            eid=self.db.entity_save(self.company_id, rec, eid); self.table.setItem(r,0,QTableWidgetItem(str(eid)))
        msg_info("Registros salvos."); self.load()
    def delete(self):
        r=self.table.currentRow()
        if r<0: return
        id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
        if not id_txt.strip().isdigit(): self.table.removeRow(r); return
        if not msg_yesno("Excluir este cadastro?"): return
        try: self.db.entity_delete(int(id_txt))
        except sqlite3.IntegrityError as e: msg_err(f"Não foi possível excluir. Existem lançamentos vinculados.\n{e}"); return
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

class TransactionsDialog(QDialog):
    # sinal para notificar alterações ao dashboard
    data_changed = pyqtSignal()

    def __init__(self, db: DB, company_id: int, user_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.user_id = user_id
        self.setWindowTitle("Lançamentos - Contas a Pagar / Receber")
        self.editing_tx_id = None

        # --- topo: escolher tipo ---
        self.rbPagar = QRadioButton("Contas a Pagar")
        self.rbReceber = QRadioButton("Contas a Receber")
        self.rbPagar.setChecked(True)
        # ao mudar o tipo, recarregar combos + grade
        self.rbPagar.toggled.connect(self.on_tipo_changed)
        self.rbReceber.toggled.connect(self.on_tipo_changed)

        top = QHBoxLayout()
        top.addWidget(self.rbPagar)
        top.addWidget(self.rbReceber)
        top.addStretch()

        # --- filtros/campos de edição ---
        self.cbEnt = QComboBox()
        self.cbCat = QComboBox()
        self.cbSub = QComboBox()
        self.cbForma = QComboBox(); self.cbForma.addItems(["Boleto", "PIX", "Transferência", "Dinheiro"])
        self.cbBanco = QComboBox()

        self.dtLanc = QDateEdit(QDate.currentDate()); set_br_date(self.dtLanc)
        self.dtVenc = QDateEdit(QDate.currentDate()); set_br_date(self.dtVenc)
        self.edDesc = QLineEdit()
        self.edValor = BRLCurrencyLineEdit(); self.edValor.setValue(0.0)
        self.spParcelas = QSpinBox(); self.spParcelas.setRange(1, 120); self.spParcelas.setValue(1)

        form = QFormLayout()
        for label, w in [
            ("Fornecedor/Cliente:", self.cbEnt),
            ("Categoria:", self.cbCat),
            ("Subcategoria:", self.cbSub),
            ("Descrição:", self.edDesc),
            ("Data Lanç.:", self.dtLanc),
            ("Data Venc.:", self.dtVenc),
            ("Forma Pagto:", self.cbForma),
            ("Qtd Parcelas:", self.spParcelas),
            ("Banco padr.:", self.cbBanco),
            ("Valor (total):", self.edValor),
        ]:
            form.addRow(label, w)

        # --- tabela ---
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Tipo", "Entidade", "Categoria", "Subcat", "Descrição", "Lançamento", "Vencimento", "Valor", "Status/Pago"]
        )
        stretch_table(self.table); zebra_table(self.table)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_menu)

        # --- botões ---
        btNovo     = QPushButton("Novo")
        btSalvar   = QPushButton("Salvar")
        btExcluir  = QPushButton("Excluir")
        btLiquidar = QPushButton("Liquidar")
        btEstornar = QPushButton("Estornar baixa")
        btPdf      = QPushButton("PDF da lista")
        btXls      = QPushButton("Excel da lista")
        for b, ic in (
            (btNovo, self.style().SP_FileDialogNewFolder),
            (btSalvar, self.style().SP_DialogSaveButton),
            (btExcluir, self.style().SP_TrashIcon),
            (btLiquidar, self.style().SP_DialogApplyButton),
            (btEstornar, self.style().SP_ArrowBack),
            (btPdf, self.style().SP_DriveDVDIcon),
            (btXls, self.style().SP_DialogSaveButton),
        ):
            b.setIcon(std_icon(self, ic))
        btNovo.clicked.connect(self.new)
        btSalvar.clicked.connect(self.save)
        btExcluir.clicked.connect(self.delete)
        btLiquidar.clicked.connect(self.liquidar)
        btEstornar.clicked.connect(self.estornar)
        btPdf.clicked.connect(lambda: export_pdf_from_table(self, self.table, "Lancamentos"))
        btXls.clicked.connect(lambda: export_excel_from_table(self, self.table, "Lancamentos"))

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(form)
        lay.addWidget(self.table)
        hl = QHBoxLayout(); [hl.addWidget(b) for b in (btNovo, btSalvar, btExcluir, btLiquidar, btEstornar, btPdf, btXls)]
        lay.addLayout(hl)

        self.populate_static()
        self.load()
        enable_autosize(self, 0.9, 0.85, 1200, 720)

    # ---------------- util ----------------
    def tipo(self) -> str:
        return "PAGAR" if self.rbPagar.isChecked() else "RECEBER"

    def on_tipo_changed(self, _checked: bool):
        """Quando alterna Pagar/Receber, filtra combos por tipo e recarrega a grade."""
        self.editing_tx_id = None
        self.reload_cats_ents()
        self.load()

    def populate_static(self):
        # bancos
        self.cbBanco.clear()
        for b in self.db.banks(self.company_id):
            self.cbBanco.addItem(f"{b['bank_name']} - {b['account_name'] or ''}", b["id"])
        # entidades/categorias/subcategorias (já filtrados por tipo)
        self.reload_cats_ents()

    def reload_cats_ents(self):
        # entidades: fornecedor para PAGAR, cliente para RECEBER
        self.cbEnt.clear()
        kind = "FORNECEDOR" if self.tipo() == "PAGAR" else "CLIENTE"
        for e in self.db.entities(self.company_id, kind):
            self.cbEnt.addItem(e["razao_social"], e["id"])

        # categorias: **somente** do tipo atual
        self.cbCat.blockSignals(True)
        self.cbCat.clear()
        for c in self.db.categories(self.company_id, self.tipo()):
            self.cbCat.addItem(c["name"], c["id"])
        self.cbCat.blockSignals(False)

        # evita múltiplas conexões do sinal
        try:
            self.cbCat.currentIndexChanged.disconnect()
        except TypeError:
            pass
        self.cbCat.currentIndexChanged.connect(self.reload_subs)

        # subcategorias da categoria atual
        self.reload_subs()

    def reload_subs(self):
        self.cbSub.clear()
        cat_id = self.cbCat.currentData()
        if not cat_id:
            return
        for s in self.db.subcategories(cat_id):
            self.cbSub.addItem(s["name"], s["id"])

    # ---------------- grade ----------------
    def load(self):
        rows = self.db.transactions(self.company_id, self.tipo())
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount(); self.table.insertRow(row)
            ent = self.db.q("SELECT razao_social FROM entities WHERE id=?", (r["entity_id"],))
            cat = self.db.q("SELECT name FROM categories WHERE id=?", (r["category_id"],))
            sub = self.db.q("SELECT name FROM subcategories WHERE id=?", (r["subcategory_id"],))
            ent_name = ent[0]["razao_social"] if ent else ""
            cat_name = cat[0]["name"] if cat else ""
            sub_name = sub[0]["name"] if sub else ""
            data = [
                r["id"], r["tipo"], ent_name, cat_name, sub_name, r["descricao"],
                iso_to_br(r["data_lanc"]), iso_to_br(r["data_venc"]),
                fmt_brl(r["valor"]), f"{r['status']} / pago {fmt_brl(r['pago'])}"
            ]
            for c, val in enumerate(data):
                it = QTableWidgetItem("" if val is None else str(val))
                if c == 0:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, c, it)

    # ---------------- ações ----------------
    def new(self):
        self.editing_tx_id = None
        self.edDesc.clear()
        self.edValor.setValue(0.0)
        self.spParcelas.setValue(1)
        self.dtLanc.setDate(QDate.currentDate())
        self.dtVenc.setDate(QDate.currentDate())

    def save(self):
        rec = dict(
            company_id=self.company_id,
            tipo=self.tipo(),
            entity_id=self.cbEnt.currentData(),
            category_id=self.cbCat.currentData(),
            subcategory_id=self.cbSub.currentData(),
            descricao=self.edDesc.text(),
            data_lanc=qdate_to_iso(self.dtLanc.date()),
            data_venc=qdate_to_iso(self.dtVenc.date()),
            forma_pagto=self.cbForma.currentText(),
            parcelas_qtd=int(self.spParcelas.value()),
            valor=self.edValor.value(),
            banco_id_padrao=self.cbBanco.currentData(),
            created_by=self.user_id,
        )
        try:
            self.db.transaction_save(rec, self.editing_tx_id)
        except sqlite3.IntegrityError as e:
            msg_err(str(e)); return
        msg_info("Lançamento salvo.")
        self.editing_tx_id = None
        self.load()
        self.data_changed.emit()  # atualiza dashboard

    def current_tx(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        tx_id = int(self.table.item(r, 0).text())
        sql = """SELECT t.*, IFNULL((SELECT SUM(p.amount+p.interest-p.discount)
                 FROM payments p WHERE p.transaction_id=t.id),0) AS pago
                 FROM transactions t WHERE t.id=?"""
        res = self.db.q(sql, (tx_id,))
        return res[0] if res else None

    def delete(self):
        tx = self.current_tx()
        if not tx:
            return
        if not msg_yesno("Excluir este lançamento?"):
            return
        try:
            self.db.transaction_delete(tx["id"])
        except sqlite3.IntegrityError as e:
            msg_err(str(e)); return
        self.load()
        self.data_changed.emit()

    def liquidar(self):
        tx = self.current_tx()
        if not tx:
            msg_err("Selecione um lançamento."); return
        dlg = PaymentDialog(self.db, self.company_id, tx, self.user_id, self)
        if dlg.exec_() and dlg.ok_clicked:
            msg_info("Baixa registrada.")
            self.load()
            self.data_changed.emit()

    def estornar(self):
        tx = self.current_tx()
        if not tx:
            return
        pays = self.db.payments_for(tx["id"])
        if not pays:
            msg_err("Não há baixas para estornar."); return
        last_id = pays[-1]["id"]
        if not msg_yesno(f"Estornar a última baixa (ID {last_id})?"):
            return
        try:
            self.db.payment_delete(last_id)
        except sqlite3.IntegrityError as e:
            msg_err(str(e)); return
        self.load()
        self.data_changed.emit()

    # ---------------- menu contextual ----------------
    def _open_menu(self, pos: QPoint):
        row = self.table.currentRow()
        if row < 0:
            return
        menu = QMenu(self)
        act_edit = menu.addAction("Editar")
        act = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if act == act_edit:
            self.edit_selected()

    def edit_selected(self):
        tx = self.current_tx()
        if not tx:
            return
        # ajusta radio sem disparar recarga dupla
        self.rbPagar.blockSignals(True); self.rbReceber.blockSignals(True)
        self.rbPagar.setChecked(tx["tipo"] == "PAGAR")
        self.rbReceber.setChecked(tx["tipo"] == "RECEBER")
        self.rbPagar.blockSignals(False); self.rbReceber.blockSignals(False)
        # garantir filtros corretos
        self.reload_cats_ents()
        set_combo_by_data(self.cbEnt, tx["entity_id"])
        set_combo_by_data(self.cbCat, tx["category_id"])
        self.reload_subs()
        set_combo_by_data(self.cbSub, tx["subcategory_id"])
        self.edDesc.setText(tx["descricao"] or "")
        self.dtLanc.setDate(QDate.fromString(tx["data_lanc"], "yyyy-MM-dd"))
        self.dtVenc.setDate(QDate.fromString(tx["data_venc"], "yyyy-MM-dd"))
        self.cbForma.setCurrentText(tx["forma_pagto"] or "Boleto")
        self.spParcelas.setValue(int(tx["parcelas_qtd"] or 1))
        set_combo_by_data(self.cbBanco, tx["banco_id_padrao"])
        self.edValor.setValue(float(tx["valor"]))
        self.editing_tx_id = int(tx["id"])

class CashflowDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Fluxo de Caixa")
        self.dtIni=QDateEdit(QDate.currentDate().addMonths(-1)); set_br_date(self.dtIni)
        self.dtFim=QDateEdit(QDate.currentDate()); set_br_date(self.dtFim)
        self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(["Data","Conta","Valor (efeito)"])
        stretch_table(self.table); zebra_table(self.table)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lbTotal=QLabel("Total: R$ 0,00")
        bt=QPushButton("Atualizar"); bt.setIcon(std_icon(self, self.style().SP_BrowserReload)); bt.clicked.connect(self.load)
        btPdf=QPushButton("Exportar PDF"); btPdf.setIcon(std_icon(self, self.style().SP_DriveDVDIcon))
        btCsv=QPushButton("Exportar Excel/CSV"); btCsv.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btPdf.clicked.connect(lambda: export_pdf_from_table(self,self.table,"Fluxo_de_Caixa"))
        btCsv.clicked.connect(lambda: export_excel_from_table(self,self.table,"Fluxo_de_Caixa"))
        form=QHBoxLayout(); form.addWidget(QLabel("Início:")); form.addWidget(self.dtIni)
        form.addWidget(QLabel("Fim:")); form.addWidget(self.dtFim); form.addWidget(bt); form.addStretch()
        lay=QVBoxLayout(self); lay.addLayout(form); lay.addWidget(self.table); lay.addWidget(self.lbTotal)
        hl=QHBoxLayout(); hl.addWidget(btPdf); hl.addWidget(btCsv); hl.addStretch(); lay.addLayout(hl)
        self.load(); enable_autosize(self, 0.8, 0.7, 1050, 600)
    def load(self):
        sql = """SELECT data, bank_name||' - '||IFNULL(account_name,'') AS conta, valor_efeito
                 FROM vw_fluxo_caixa
                 WHERE company_id=? AND date(data) BETWEEN date(?) AND date(?)
                 ORDER BY date(data)"""
        params=(self.company_id, qdate_to_iso(self.dtIni.date()), qdate_to_iso(self.dtFim.date()))
        rows=self.db.q(sql, params); self.table.setRowCount(0); total=0.0
        for r in rows:
            row=self.table.rowCount(); self.table.insertRow(row)
            total += float(r["valor_efeito"])
            self.table.setItem(row,0,QTableWidgetItem(iso_to_br(r["data"])))
            self.table.setItem(row,1,QTableWidgetItem(r["conta"]))
            self.table.setItem(row,2,QTableWidgetItem(fmt_brl(r["valor_efeito"])))
        self.lbTotal.setText(f"Total: {fmt_brl(total)}")

# ===== [SUBSTITUA A CLASSE DREDialog INTEIRA POR ESTA] ======================
class DREDialog(QDialog):
    """
    DRE com layout do print:
    - Tela elástica (acompanha o tamanho da janela).
    - PDF ocupa 100% da largura útil.
    - Exportar Excel/CSV reativado.
    """
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.setWindowTitle("Demonstração de Resultado (DRE)")

        self._last_rows = []

        # Filtros
        self.spAno = QSpinBox();  self.spAno.setRange(2000, 2099); self.spAno.setValue(date.today().year)
        self.spMes = QSpinBox();  self.spMes.setRange(0, 12);      self.spMes.setValue(0)   # 0 = todos
        self.cbReg = QComboBox(); self.cbReg.addItems(["COMPETENCIA", "CAIXA"])

        btGerar = QPushButton("Gerar"); btGerar.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btGerar.clicked.connect(self.load)

        btPdf = QPushButton("Exportar PDF"); btPdf.setIcon(std_icon(self, self.style().SP_DriveDVDIcon))
        btPdf.clicked.connect(self.export_pdf)

        btXls = QPushButton("Exportar Excel/CSV"); btXls.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btXls.clicked.connect(self.export_excel)

        # Visualização (somente leitura)
        self.view = QTextEdit(); self.view.setReadOnly(True)
        self.view.setStyleSheet("QTextEdit{background:#ffffff;}")

        top = QHBoxLayout()
        top.addWidget(QLabel("Ano:")); top.addWidget(self.spAno)
        top.addSpacing(8)
        top.addWidget(QLabel("Mês (0=todos):")); top.addWidget(self.spMes)
        top.addSpacing(8)
        top.addWidget(QLabel("Regime:")); top.addWidget(self.cbReg)
        top.addSpacing(12)
        top.addWidget(btGerar)
        top.addStretch()

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.view)
        hl = QHBoxLayout(); hl.addWidget(btPdf); hl.addWidget(btXls); hl.addStretch(); lay.addLayout(hl)

        enable_autosize(self, 0.85, 0.75, 1100, 650)
        self.load()

    # ---------- largura elástica na tela ----------
    def _content_width(self) -> int:
        try:
            w = self.view.viewport().width()
        except Exception:
            w = self.width()
        return max(720, min(1200, w - 40))  # limites

    # ---------- HTML (tela ou PDF) ----------
    def _build_html(self, rows, width_px: int = None, for_pdf: bool = False) -> str:
        rec_rows  = [r for r in rows if (r["tipo"] == "RECEBER")]
        pag_rows  = [r for r in rows if (r["tipo"] == "PAGAR")]

        total_receber = sum(float(r["total"] or 0) for r in rec_rows)
        total_pagar   = sum(float(r["total"] or 0) for r in pag_rows)
        retencoes     = 0.0  # placeholder

        margem = total_receber - retencoes - total_pagar
        perc   = (margem / total_receber * 100.0) if total_receber else 0.0
        perc_txt = f"{perc:,.1f}%".replace(".", ",")

        def money(v): return fmt_brl(abs(v))

        # largura da tabela
        if for_pdf:
            # para PDF queremos um valor em px (ex.: 760) pra caber nas margens de 800x800
            width_px = width_px or 760
            wrap_w = f"{width_px}px"
            col_cat = f"{int(width_px*0.68)}px"
            col_val = f"{int(width_px*0.32)}px"
            base_font = "12px"
        else:
            width_px = width_px or 900
            wrap_w = f"{width_px}px"
            col_cat = f"{int(width_px*0.68)}px"
            col_val = f"{int(width_px*0.32)}px"
            base_font = "13px"

        css = f"""
        <style>
        body{{font-family:Arial,Helvetica,sans-serif;}}
        table.wrap{{width:{wrap_w}; margin:10px auto; border:3px solid #000; border-collapse:collapse;}}
        .wrap th,.wrap td{{border:1px solid #000; padding:8px 10px; font-size:{base_font};}}
        .sec{{background:#eee; font-weight:700; font-style:italic; text-align:center;}}
        .head{{background:#ddd; font-weight:700;}}
        .right{{text-align:right;}}
        .center{{text-align:center;}}
        .nowrap{{white-space:nowrap;}}
        .col-cat{{width:{col_cat};}}
        .col-val{{width:{col_val};}}
        .total{{font-weight:700;}}
        .percent{{font-weight:700; font-size:14px;}}
        </style>
        """

        html = [css, '<table class="wrap">']
        # (resto do HTML exatamente como está na sua versão atual)
        # -----------------------------------------------------------------
        html += [
            '<tr><th class="sec" colspan="2">CONTAS A RECEBER</th></tr>',
            '<tr class="head"><th class="nowrap col-cat">CATEGORIA</th><th class="right nowrap col-val">VALOR</th></tr>'
        ]
        for r in rec_rows:
            html.append(
                f'<tr><td class="col-cat">{(r["categoria"] or "").upper()}</td>'
                f'<td class="right col-val">{money(float(r["total"]))}</td></tr>'
            )
        html += [
            '<tr class="sec"><th colspan="2">RETENÇÕES DE IMPOSTOS</th></tr>',
            '<tr><td class="col-cat">IMPOSTO RETIDO</td><td class="right col-val">&nbsp;</td></tr>'
        ]
        html += [
            '<tr class="sec"><th colspan="2">CONTAS A PAGAR</th></tr>',
            '<tr class="head"><th class="nowrap col-cat">CATEGORIA</th><th class="right nowrap col-val">VALOR</th></tr>'
        ]
        for r in pag_rows:
            val = float(r["total"])
            html.append(
                f'<tr><td class="col-cat">{(r["categoria"] or "").upper()}</td>'
                f'<td class="right col-val">-{money(val)}</td></tr>'
            )
        html += [
            '<tr class="sec"><th colspan="2">MARGEM LIQUIDA</th></tr>',
            f'<tr class="total"><td class="col-cat"></td><td class="right col-val">{fmt_brl(margem)}</td></tr>',
            f'<tr><td class="center percent" colspan="2">{perc_txt}</td></tr>',
            '</table>'
        ]
        return "\n".join(html)

    def load(self):
        mes = self.spMes.value() or None
        rows = self.db.dre(self.company_id, self.spAno.value(), mes, self.cbReg.currentText())
        self._last_rows = rows[:]
        html = self._build_html(rows, self._content_width(), for_pdf=False)
        self.view.setHtml(html)

    def export_pdf(self):
        rows = self._last_rows[:] if self._last_rows else []
        html = self._build_html(rows, for_pdf=True)  # largura 100% para PDF
        export_pdf_from_html(self, html, "DRE")

    def export_excel(self):
        """Gera uma folha simples: Categoria | Tipo | Valor (+ totais)."""
        rows = self._last_rows[:] if self._last_rows else []
        tmp = QTableWidget(0, 3)
        tmp.setHorizontalHeaderLabels(["Categoria", "Tipo", "Valor"])
        rec = 0.0; pag = 0.0
        for r in rows:
            row = tmp.rowCount(); tmp.insertRow(row)
            val = float(r["total"] or 0)
            tmp.setItem(row, 0, QTableWidgetItem(str(r["categoria"] or "")))
            tmp.setItem(row, 1, QTableWidgetItem("RECEBER" if r["tipo"] == "RECEBER" else "PAGAR"))
            tmp.setItem(row, 2, QTableWidgetItem(fmt_brl(val if r["tipo"] == "RECEBER" else -val)))
            if r["tipo"] == "RECEBER": rec += val
            else: pag += val

        # separador + totais
        if rows:
            tmp.insertRow(tmp.rowCount())
            row = tmp.rowCount(); tmp.insertRow(row)
            tmp.setItem(row, 0, QTableWidgetItem("TOTAL RECEBER"))
            tmp.setItem(row, 2, QTableWidgetItem(fmt_brl(rec)))
            row = tmp.rowCount(); tmp.insertRow(row)
            tmp.setItem(row, 0, QTableWidgetItem("TOTAL PAGAR"))
            tmp.setItem(row, 2, QTableWidgetItem(fmt_brl(-pag)))
            margem = rec - pag
            row = tmp.rowCount(); tmp.insertRow(row)
            tmp.setItem(row, 0, QTableWidgetItem("MARGEM LÍQUIDA"))
            tmp.setItem(row, 2, QTableWidgetItem(fmt_brl(margem)))

        export_excel_from_table(self, tmp, "DRE")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._last_rows:
            self.view.setHtml(self._build_html(self._last_rows, self._content_width(), for_pdf=False))

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

        # carrega permissões do usuário
        self.allowed_codes = self.db.allowed_codes(self.user['id'], self.company_id)

        comp = self.db.q("SELECT razao_social FROM companies WHERE id=?", (company_id,))[0]["razao_social"]
        self.setWindowTitle(f"{APP_TITLE} - {comp}")

        menubar = self.menuBar()

        # ===== Cadastros (só cria se houver ação)
        cad_actions = []
        actBanks = QAction("Bancos", self);            actBanks.triggered.connect(self.open_banks)
        actEnts  = QAction("Fornecedores/Clientes", self); actEnts.triggered.connect(self.open_entities)
        actCats  = QAction("Categorias/Subcategorias", self); actCats.triggered.connect(self.open_categories)

        if self.has("BANCOS"):               cad_actions.append(actBanks)
        if self.has("FORNECEDOR_CLIENTE"):   cad_actions.append(actEnts)
        if self.has("CONTAS"):               cad_actions.append(actCats)

        if self.db.is_admin(self.user['id']):
            actEmpAdmin  = QAction("Empresas (admin)", self); actEmpAdmin.triggered.connect(self.open_companies_admin)
            actUserAdmin = QAction("Usuários (admin)", self);  actUserAdmin.triggered.connect(self.open_users_admin)
            if cad_actions:
                cad_actions.append(None)
            cad_actions.extend([actEmpAdmin, actUserAdmin])

        if cad_actions:
            mCad = menubar.addMenu("Cadastros")
            for a in cad_actions:
                mCad.addSeparator() if a is None else mCad.addAction(a)

        # ===== Movimentação
        mov_actions = []
        actTx = QAction("Lançamentos (Pagar/Receber)", self); actTx.triggered.connect(self.open_transactions)
        if self.has("CONTAS"): mov_actions.append(actTx)
        if mov_actions:
            mMov = menubar.addMenu("Movimentação")
            for a in mov_actions: mMov.addAction(a)

        # ===== Relatórios
        rel_actions = []
        actFluxo = QAction("Fluxo de Caixa", self); actFluxo.triggered.connect(self.open_cashflow)
        actDre   = QAction("DRE", self);           actDre.triggered.connect(self.open_dre)
        if self.has("CONTAS"): rel_actions.append(actFluxo)
        if self.has("DRE"):    rel_actions.append(actDre)
        if rel_actions:
            mRel = menubar.addMenu("Relatórios")
            for a in rel_actions: mRel.addAction(a)

        # ===== Sair
        actSair = QAction("Sair", self); actSair.triggered.connect(self.close)
        menubar.addAction(actSair)

        # -------- Dashboard
        w = QWidget(); v = QVBoxLayout(w)
        title_row = QHBoxLayout()
        lbTitle = QLabel("Sistema de Gestão Financeira"); lbTitle.setStyleSheet("font-size:26px;font-weight:600;")
        lbCompany = QLabel(comp); lbCompany.setStyleSheet("font-size:12px;font-style:italic;color:#444;")
        title_row.addWidget(lbTitle); title_row.addStretch(); title_row.addWidget(lbCompany)
        v.addLayout(title_row)

        center = QHBoxLayout()
        left = QVBoxLayout(); left.addStretch(1)
        filter_box = QHBoxLayout()
        self.cbMes = QComboBox()
        self.cbMes.addItems(["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"])
        self.spAno = QSpinBox(); self.spAno.setRange(2000,2099); self.spAno.setValue(date.today().year)
        filter_box.addWidget(QLabel("Período:")); filter_box.addWidget(self.cbMes)
        filter_box.addSpacing(12); filter_box.addWidget(QLabel("Ano:")); filter_box.addWidget(self.spAno)
        left.addLayout(filter_box); center.addLayout(left,1)

        right = QVBoxLayout()
        panel = QGroupBox(""); panel_l = QVBoxLayout(panel)
        grpR = QGroupBox("Contas a Receber"); lr = QVBoxLayout(grpR)
        self.lbReceber = QLabel("R$ 0,00"); self.lbReceber.setAlignment(Qt.AlignCenter)
        self.lbReceber.setStyleSheet("QLabel{font-size:28px;font-weight:700;color:#0a8f3c;border:1px solid #999;border-radius:10px;padding:12px;background:#fff;}")
        lr.addWidget(self.lbReceber)
        grpP = QGroupBox("Contas a Pagar"); lp = QVBoxLayout(grpP)
        self.lbPagar = QLabel("-R$ 0,00"); self.lbPagar.setAlignment(Qt.AlignCenter)
        self.lbPagar.setStyleSheet("QLabel{font-size:28px;font-weight:700;color:#b32020;border:1px solid #999;border-radius:10px;padding:12px;background:#fff;}")
        lp.addWidget(self.lbPagar)
        panel_l.addWidget(grpR); panel_l.addWidget(grpP)
        right.addWidget(panel,3); center.addLayout(right,2)
        v.addLayout(center)
        self.setCentralWidget(w)

        self.cbMes.currentIndexChanged.connect(self.update_dashboard)
        self.spAno.valueChanged.connect(self.update_dashboard)
        self.cbMes.setCurrentIndex(date.today().month-1)
        self.update_dashboard()

        enable_autosize(self, 0.95, 0.9, 1280, 740)

    # ---------- helpers de permissão ----------
    def has(self, code: str) -> bool:
        """True se usuário tem a permissão indicada ou for admin."""
        return self.db.is_admin(self.user['id']) or (code in self.allowed_codes)

    def ensure(self, code: str) -> bool:
        if not self.has(code):
            msg_err("Você não tem permissão para acessar esta função.")
            return False
        return True

    # ---------- dashboard ----------
    def periodo_atual(self):
        ano = self.spAno.value(); mes = self.cbMes.currentIndex() + 1
        dt_ini = date(ano, mes, 1)
        dt_next = date(ano + (1 if mes == 12 else 0), 1 if mes == 12 else mes + 1, 1)
        return dt_ini.isoformat(), dt_next.isoformat()

    def update_dashboard(self):
        dt_ini, dt_fim_excl = self.periodo_atual()
        resumo = self.db.resumo_periodo(self.company_id, dt_ini, dt_fim_excl)
        self.lbReceber.setText(fmt_brl(resumo.get('RECEBER', 0.0)))
        self.lbPagar.setText("-" + fmt_brl(resumo.get('PAGAR', 0.0)).replace("R$ ","R$ "))

    # ---------- handlers (checando permissão) ----------
    def open_banks(self):
        if self.ensure("BANCOS"): BanksDialog(self.db, self.company_id, self).exec_()

    def open_entities(self):
        if self.ensure("FORNECEDOR_CLIENTE"): EntitiesDialog(self.db, self.company_id, self).exec_()

    def open_categories(self):
        if self.ensure("CONTAS"): CategoriesDialog(self.db, self.company_id, self).exec_()

    def open_transactions(self):
        if not self.ensure("CONTAS"):
            return
        dlg = TransactionsDialog(self.db, self.company_id, self.user["id"], self)
        # atualiza dashboard sempre que houver mudança, mesmo com o diálogo aberto
        dlg.data_changed.connect(self.update_dashboard)
        dlg.exec_()
        # garante atualização ao fechar também
        self.update_dashboard()

    def open_cashflow(self):
        if self.ensure("CONTAS"): CashflowDialog(self.db, self.company_id, self).exec_()

    def open_dre(self):
        if self.ensure("DRE"): DREDialog(self.db, self.company_id, self).exec_()

    # ---------- admin ----------
    def open_companies_admin(self):
        if not self.db.is_admin(self.user['id']):
            msg_err("Somente administrador."); return
        CompaniesDialog(self.db, self).exec_()

    def open_users_admin(self):
        if not self.db.is_admin(self.user['id']):
            msg_err("Somente administrador."); return
        UsersDialog(self.db, self).exec_()

# =============================================================================
def main():
    conn=ensure_db(); db=DB(conn)
    app=QApplication(sys.argv)
    login=LoginWindow(db); login.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
