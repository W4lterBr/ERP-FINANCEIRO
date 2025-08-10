# app_erp.py
# =============================================================================
# ERP Financeiro - PyQt5 (com máscaras, ícones e exportar PDF/Excel)
# =============================================================================


import os
import sys
import csv
import re
import sqlite3
from pathlib import Path
from datetime import date
import hashlib
try:
    from hmac import compare_digest as secure_eq
except Exception:
    from secrets import compare_digest as secure_eq

from PyQt5.QtCore import Qt, QDate, QRegExp
from PyQt5.QtGui import QRegExpValidator, QIcon, QPainter, QTextDocument
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QComboBox, QLineEdit, QPushButton, QHBoxLayout,
    QVBoxLayout, QFormLayout, QMessageBox, QMainWindow, QAction, QDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QSpinBox, QDateEdit, QCheckBox, QRadioButton,
    QFileDialog, QStyledItemDelegate, QAbstractScrollArea
)
from PyQt5.QtPrintSupport import QPrinter

DB_FILE = "erp_financeiro.db"
APP_TITLE = "ERP Financeiro"

# ----------------------------------------------------------------------------- 
# ========= NOVO: utilitários de auto-ajuste =========
# -----------------------------------------------------------------------------
def enable_autosize(widget, w_ratio=0.75, h_ratio=0.7, min_w=900, min_h=600):
    """
    Torna a janela redimensionável, com min/max buttons e tamanho baseado na tela.
    Use em todas as janelas e diálogos após montar o layout.
    """
    # habilita maximizar/minimizar
    try:
        widget.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        widget.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
    except Exception:
        pass
    # alguns QDialogs suportam size grip
    if isinstance(widget, QDialog):
        try:
            widget.setSizeGripEnabled(True)
        except Exception:
            pass
    # dimensiona conforme a tela
    scr = QApplication.primaryScreen()
    if scr:
        g = scr.availableGeometry()
        w = max(min_w, int(g.width() * float(w_ratio)))
        h = max(min_h, int(g.height() * float(h_ratio)))
        widget.resize(w, h)
    else:
        widget.resize(min_w, min_h)

def stretch_table(table: QTableWidget):
    """Ajusta tabela para sempre ocupar o espaço e evitar campos cortados."""
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.Stretch)
    table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
    table.setMinimumHeight(300)

# ----------------------------------------------------------------------------- 
# Utilidades: formatação e validação BR (mesmo de antes)
# -----------------------------------------------------------------------------
UF_SET = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA",
    "PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}
def only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())
def format_cnpj(d: str) -> str:
    d = only_digits(d);  return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}" if len(d)==14 else d
def format_cpf(d: str) -> str:
    d = only_digits(d);  return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}" if len(d)==11 else d
def validate_cnpj(cnpj: str) -> bool:
    d = only_digits(cnpj)
    if len(d) != 14 or d == d[0]*14: return False
    def dv(nums, w): 
        t = sum(int(n)*ww for n,ww in zip(nums,w)); r = t%11
        return '0' if r<2 else str(11-r)
    w1=[5,4,3,2,9,8,7,6,5,4,3,2]; w2=[6]+w1
    return d[-2:]==dv(d[:12],w1)+dv(d[:12]+dv(d[:12],w1),w2)
def validate_cpf(cpf: str) -> bool:
    d = only_digits(cpf)
    if len(d)!=11 or d==d[0]*11: return False
    def dv(nums,m): 
        s=sum(int(nums[i])*(m-i) for i in range(len(nums))); r=(s*10)%11
        return '0' if r==10 else str(r)
    return d[-2:]==dv(d[:9],10)+dv(d[:9]+dv(d[:9],10),11)
def validate_cep(cep: str) -> bool:
    return len(only_digits(cep)) == 8
def validate_uf(uf: str) -> bool:
    return (uf or "").upper() in UF_SET

# ----------------------------------------------------------------------------- 
# Delegates para máscaras no QTableWidget (mesmo de antes)
# -----------------------------------------------------------------------------
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

# ----------------------------------------------------------------------------- 
# Esquema/Seed/DB – (idêntico ao anterior)
# -----------------------------------------------------------------------------
SCHEMA_SQL = r"""  -- [conteúdo idêntico ao seu script anterior, sem mudanças] """
SEED_SQL = r"""    -- [conteúdo idêntico ao seu script anterior, sem mudanças] """

# ----------------------------------------------------------------------------- 
# Esquema do banco
# -----------------------------------------------------------------------------
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
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  company_id INTEGER NOT NULL,
  payment_date TEXT NOT NULL,
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
  user_id INTEGER, action TEXT NOT NULL, table_name TEXT NOT NULL,
  record_id INTEGER, details TEXT
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
CREATE TRIGGER IF NOT EXISTS trg_trans_before_ins_period
BEFORE INSERT ON transactions
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=NEW.company_id
      AND p.month=CAST(strftime('%m',NEW.data_lanc) AS INTEGER)
      AND p.year =CAST(strftime('%Y',NEW.data_lanc) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado para lançamentos') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_trans_before_upd_period
BEFORE UPDATE ON transactions
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=OLD.company_id
      AND p.month=CAST(strftime('%m',OLD.data_lanc) AS INTEGER)
      AND p.year =CAST(strftime('%Y',OLD.data_lanc) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado (registro original)') END;
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=NEW.company_id
      AND p.month=CAST(strftime('%m',NEW.data_lanc) AS INTEGER)
      AND p.year =CAST(strftime('%Y',NEW.data_lanc) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado (registro novo)') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_trans_before_del_period
BEFORE DELETE ON transactions
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=OLD.company_id
      AND p.month=CAST(strftime('%m',OLD.data_lanc) AS INTEGER)
      AND p.year =CAST(strftime('%Y',OLD.data_lanc) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado para exclusão') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_pay_before_ins_period
BEFORE INSERT ON payments
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=NEW.company_id
      AND p.month=CAST(strftime('%m',NEW.payment_date) AS INTEGER)
      AND p.year =CAST(strftime('%Y',NEW.payment_date) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado para baixas') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_pay_before_upd_period
BEFORE UPDATE ON payments
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=OLD.company_id
      AND p.month=CAST(strftime('%m',OLD.payment_date) AS INTEGER)
      AND p.year =CAST(strftime('%Y',OLD.payment_date) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado (baixa original)') END;
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=NEW.company_id
      AND p.month=CAST(strftime('%m',NEW.payment_date) AS INTEGER)
      AND p.year =CAST(strftime('%Y',NEW.payment_date) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado (baixa nova)') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_pay_before_del_period
BEFORE DELETE ON payments
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM periods p
    WHERE p.company_id=OLD.company_id
      AND p.month=CAST(strftime('%m',OLD.payment_date) AS INTEGER)
      AND p.year =CAST(strftime('%Y',OLD.payment_date) AS INTEGER)
      AND p.status='CLOSED')
  THEN RAISE(ABORT,'Periodo fechado para exclusão de baixa') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_pay_after_ins_bank_status
AFTER INSERT ON payments
BEGIN
  UPDATE bank_accounts
     SET current_balance = current_balance + (
       SELECT CASE WHEN t.tipo='RECEBER'
                   THEN (NEW.amount + NEW.interest - NEW.discount)
                   ELSE -(NEW.amount + NEW.interest - NEW.discount) END
       FROM transactions t WHERE t.id=NEW.transaction_id)
   WHERE id=NEW.bank_id;
  UPDATE transactions
     SET status = CASE
         WHEN (SELECT ROUND(SUM(p.amount+p.interest-p.discount),2)
               FROM payments p WHERE p.transaction_id=NEW.transaction_id) >= ROUND(valor,2)
         THEN 'LIQUIDADO' ELSE 'EM_ABERTO' END,
         updated_at=datetime('now')
   WHERE id=NEW.transaction_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_pay_after_upd_bank_status
AFTER UPDATE ON payments
BEGIN
  UPDATE bank_accounts
     SET current_balance = current_balance - (
       SELECT CASE WHEN t.tipo='RECEBER'
                   THEN (OLD.amount + OLD.interest - OLD.discount)
                   ELSE -(OLD.amount + OLD.interest - OLD.discount) END
       FROM transactions t WHERE t.id=OLD.transaction_id)
   WHERE id=OLD.bank_id;
  UPDATE bank_accounts
     SET current_balance = current_balance + (
       SELECT CASE WHEN t.tipo='RECEBER'
                   THEN (NEW.amount + NEW.interest - NEW.discount)
                   ELSE -(NEW.amount + NEW.interest - NEW.discount) END
       FROM transactions t WHERE t.id=NEW.transaction_id)
   WHERE id=NEW.bank_id;
  UPDATE transactions
     SET status = CASE
         WHEN (SELECT ROUND(SUM(p.amount+p.interest-p.discount),2)
               FROM payments p WHERE p.transaction_id=OLD.transaction_id) >= ROUND(valor,2)
         THEN 'LIQUIDADO' ELSE 'EM_ABERTO' END,
         updated_at=datetime('now')
   WHERE id=OLD.transaction_id;
  UPDATE transactions
     SET status = CASE
         WHEN (SELECT ROUND(SUM(p.amount+p.interest-p.discount),2)
               FROM payments p WHERE p.transaction_id=NEW.transaction_id) >= ROUND(valor,2)
         THEN 'LIQUIDADO' ELSE 'EM_ABERTO' END,
         updated_at=datetime('now')
   WHERE id=NEW.transaction_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_pay_after_del_bank_status
AFTER DELETE ON payments
BEGIN
  UPDATE bank_accounts
     SET current_balance = current_balance - (
       SELECT CASE WHEN t.tipo='RECEBER'
                   THEN (OLD.amount + OLD.interest - OLD.discount)
                   ELSE -(OLD.amount + OLD.interest - OLD.discount) END
       FROM transactions t WHERE t.id=OLD.transaction_id)
   WHERE id=OLD.bank_id;
  UPDATE transactions
     SET status = CASE
         WHEN (SELECT ROUND(SUM(p.amount+p.interest-p.discount),2)
               FROM payments p WHERE p.transaction_id=OLD.transaction_id) >= ROUND(valor,2)
         THEN 'LIQUIDADO' ELSE 'EM_ABERTO' END,
         updated_at=datetime('now')
   WHERE id=OLD.transaction_id;
END;
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
INSERT OR IGNORE INTO periods(company_id, month, year, status)
VALUES(1, CAST(strftime('%m','now') AS INTEGER), CAST(strftime('%Y','now') AS INTEGER),'OPEN');
"""

# -----------------------------------------------------------------------------
# Hash PBKDF2 / conexão (igual)
# -----------------------------------------------------------------------------
def pbkdf2_hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

def ensure_db():
    path = Path(DB_FILE); first = not path.exists()
    conn = sqlite3.connect(path); conn.execute("PRAGMA foreign_keys = ON;")
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
        for (pid,) in conn.execute("SELECT id FROM permission_types"):  # dá todas permissões ao admin
            conn.execute("INSERT OR REPLACE INTO user_permissions(user_id, perm_id, allowed) VALUES(?,?,1)",
                         (admin_id, pid))
        conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('schema_version','1')")
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn

# -----------------------------------------------------------------------------
# Camada de dados (DB) – igual ao anterior
# -----------------------------------------------------------------------------
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
        sql = """
            SELECT u.id, u.name, u.username
            FROM users u
            JOIN user_company_access a ON a.user_id=u.id
            WHERE a.company_id=? AND u.active=1
            ORDER BY u.name
        """
        return self.q(sql, (company_id,))

    def verify_login(self, company_id, username, password):
        r = self.q("SELECT * FROM users WHERE username=? AND active=1", (username,))
        if not r:
            return None
        u = r[0]
        calc = pbkdf2_hash(password, u["password_salt"], u["iterations"])
        if not secure_eq(calc, u["password_hash"]):
            return None
        ok = self.q("SELECT 1 FROM user_company_access WHERE user_id=? AND company_id=?", (u["id"], company_id))
        if not ok:
            return None
        return u

    def is_admin(self, user_id):
        r = self.q("SELECT is_admin FROM users WHERE id=?", (user_id,))
        return bool(r and r[0]["is_admin"])

    def user_permissions(self, user_id):
        rows = self.q("""
            SELECT pt.code, up.allowed
              FROM permission_types pt
              LEFT JOIN user_permissions up
                     ON up.perm_id=pt.id AND up.user_id=?
        """, (user_id,))
        perms = {}
        for row in rows:
            perms[row["code"]] = bool(row["allowed"])
        return perms

    # Companies
    def companies_all(self):
        return self.q("SELECT * FROM companies ORDER BY razao_social")

    def company_save(self, data, company_id=None):
        if company_id:
            sql = """UPDATE companies SET cnpj=?, razao_social=?, contato1=?, contato2=?, rua=?,
                     bairro=?, numero=?, cep=?, uf=?, cidade=?, email=?, active=? WHERE id=?"""
            self.e(sql, (data["cnpj"], data["razao"], data["contato1"], data["contato2"], data["rua"],
                         data["bairro"], data["numero"], data["cep"], data["uf"], data["cidade"],
                         data["email"], data["active"], company_id))
            return company_id
        sql = """INSERT INTO companies(cnpj,razao_social,contato1,contato2,rua,bairro,numero,cep,uf,cidade,email,active)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"""
        return self.e(sql, (data["cnpj"], data["razao"], data["contato1"], data["contato2"], data["rua"],
                            data["bairro"], data["numero"], data["cep"], data["uf"], data["cidade"],
                            data["email"], data["active"]))

    def company_delete(self, company_id):
        self.e("DELETE FROM companies WHERE id=?", (company_id,))

    # Users
    def users_all(self):
        return self.q("SELECT * FROM users ORDER BY name")

    def user_save(self, data, user_id=None, reset_password=None):
        if user_id:
            self.e("""UPDATE users SET name=?, username=?, is_admin=?, active=? WHERE id=?""",
                   (data["name"], data["username"], int(data["is_admin"]), int(data["active"]), user_id))
            if reset_password:
                salt = os.urandom(16)
                iters = 240_000
                pw_hash = pbkdf2_hash(reset_password, salt, iters)
                self.e("UPDATE users SET password_salt=?, password_hash=?, iterations=? WHERE id=?",
                       (salt, pw_hash, iters, user_id))
        else:
            salt = os.urandom(16)
            iters = 240_000
            pw_hash = pbkdf2_hash(data["password"], salt, iters)
            user_id = self.e("""INSERT INTO users(name, username, password_salt, password_hash, iterations, is_admin, active)
                                VALUES(?,?,?,?,?,?,?)""",
                             (data["name"], data["username"], salt, pw_hash, iters, int(data["is_admin"]), 1))
        self.e("DELETE FROM user_company_access WHERE user_id=?", (user_id,))
        for cid in data["companies"]:
            self.e("INSERT INTO user_company_access(user_id, company_id) VALUES(?,?)", (user_id, cid))
        self.e("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
        perm_ids = self.q("SELECT id, code FROM permission_types")
        code_to_id = {p["code"]: p["id"] for p in perm_ids}
        for code, allowed in data["perms"].items():
            self.e("INSERT INTO user_permissions(user_id, perm_id, allowed) VALUES(?,?,?)",
                   (user_id, code_to_id[code], 1 if allowed else 0))
        return user_id

    def user_delete(self, user_id):
        self.e("DELETE FROM users WHERE id=?", (user_id,))

    # Banks
    def banks(self, company_id):
        return self.q("SELECT * FROM bank_accounts WHERE company_id=? ORDER BY bank_name, account_name", (company_id,))

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

    def bank_delete(self, bank_id):
        self.e("DELETE FROM bank_accounts WHERE id=?", (bank_id,))

    # Entities
    def entities(self, company_id, kind=None):
        if kind:
            return self.q("SELECT * FROM entities WHERE company_id=? AND (kind=? OR kind='AMBOS') ORDER BY razao_social",
                          (company_id, kind))
        return self.q("SELECT * FROM entities WHERE company_id=? ORDER BY razao_social", (company_id,))

    def entity_save(self, company_id, rec, entity_id=None):
        if entity_id:
            self.e("""UPDATE entities SET kind=?, cnpj_cpf=?, razao_social=?, contato1=?, contato2=?, rua=?, bairro=?,
                      numero=?, cep=?, uf=?, cidade=?, email=?, active=? WHERE id=?""",
                   (rec["kind"], rec["cnpj_cpf"], rec["razao_social"], rec["contato1"], rec["contato2"], rec["rua"], rec["bairro"],
                    rec["numero"], rec["cep"], rec["uf"], rec["cidade"], rec["email"], int(rec["active"]), entity_id))
            return entity_id
        return self.e("""INSERT INTO entities(company_id,kind,cnpj_cpf,razao_social,contato1,contato2,rua,bairro,numero,
                                             cep,uf,cidade,email,active)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (company_id, rec["kind"], rec["cnpj_cpf"], rec["razao_social"], rec["contato1"], rec["contato2"], rec["rua"],
                        rec["bairro"], rec["numero"], rec["cep"], rec["uf"], rec["cidade"], rec["email"], int(rec["active"])))

    def entity_delete(self, entity_id):
        self.e("DELETE FROM entities WHERE id=?", (entity_id,))

    # Categories
    def categories(self, company_id, tipo=None):
        if tipo:
            return self.q("SELECT * FROM categories WHERE company_id=? AND tipo=? ORDER BY name", (company_id, tipo))
        return self.q("SELECT * FROM categories WHERE company_id=? ORDER BY tipo, name", (company_id,))

    def subcategories(self, category_id):
        return self.q("SELECT * FROM subcategories WHERE category_id=? ORDER BY name", (category_id,))

    def category_save(self, company_id, name, tipo, cat_id=None):
        if cat_id:
            self.e("UPDATE categories SET name=?, tipo=? WHERE id=?", (name, tipo, cat_id))
            return cat_id
        return self.e("INSERT INTO categories(company_id,name,tipo) VALUES(?,?,?)", (company_id, name, tipo))

    def subcategory_save(self, category_id, name, sub_id=None):
        if sub_id:
            self.e("UPDATE subcategories SET name=? WHERE id=?", (name, sub_id))
            return sub_id
        return self.e("INSERT INTO subcategories(category_id,name) VALUES(?,?)", (category_id, name))

    def category_delete(self, cat_id):
        self.e("DELETE FROM categories WHERE id=?", (cat_id,))

    def subcategory_delete(self, sub_id):
        self.e("DELETE FROM subcategories WHERE id=?", (sub_id,))

    # Transactions & Payments
    def transactions(self, company_id, tipo=None):
        base = """
            SELECT t.*,
                   IFNULL((SELECT SUM(p.amount+p.interest-p.discount)
                           FROM payments p WHERE p.transaction_id=t.id),0) AS pago
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
            sql = """UPDATE transactions SET tipo=?, entity_id=?, category_id=?, subcategory_id=?, descricao=?,
                     data_lanc=?, data_venc=?, forma_pagto=?, parcelas_qtd=?, valor=?, banco_id_padrao=?, updated_at=datetime('now')
                     WHERE id=?"""
            self.e(sql, (rec["tipo"], rec["entity_id"], rec["category_id"], rec["subcategory_id"], rec["descricao"],
                         rec["data_lanc"], rec["data_venc"], rec["forma_pagto"], int(rec["parcelas_qtd"]), float(rec["valor"]),
                         rec["banco_id_padrao"], tx_id))
            return tx_id
        sql = """INSERT INTO transactions(company_id,tipo,entity_id,category_id,subcategory_id,descricao,
                                          data_lanc,data_venc,forma_pagto,parcelas_qtd,valor,status,
                                          banco_id_padrao,created_by)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,'EM_ABERTO',?,?)"""
        return self.e(sql, (rec["company_id"], rec["tipo"], rec["entity_id"], rec["category_id"], rec["subcategory_id"],
                            rec["descricao"], rec["data_lanc"], rec["data_venc"], rec["forma_pagto"],
                            int(rec["parcelas_qtd"]), float(rec["valor"]), rec["banco_id_padrao"], rec["created_by"]))

    def transaction_delete(self, tx_id):
        self.e("DELETE FROM transactions WHERE id=?", (tx_id,))

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

    def payment_delete(self, payment_id):
        self.e("DELETE FROM payments WHERE id=?", (payment_id,))

    # Periods
    def period_status(self, company_id, month, year):
        r = self.q("SELECT status FROM periods WHERE company_id=? AND month=? AND year=?", (company_id, month, year))
        if not r:
            return "OPEN"
        return r[0]["status"]

    def period_set(self, company_id, month, year, status, user_id):
        r = self.q("SELECT id FROM periods WHERE company_id=? AND month=? AND year=?", (company_id, month, year))
        if r:
            self.e("UPDATE periods SET status=?, locked_at=datetime('now'), locked_by=? WHERE id=?",
                   (status, user_id, r[0]["id"]))
        else:
            self.e("INSERT INTO periods(company_id,month,year,status,locked_at,locked_by) VALUES(?,?,?,?,datetime('now'),?)",
                   (company_id, month, year, status, user_id))

    # DRE
    def dre(self, company_id, ano, mes=None, regime='COMPETENCIA'):
        src = "vw_dre_competencia" if regime == 'COMPETENCIA' else "vw_dre_caixa"
        params = [company_id, str(ano)]
        filt = ""
        if mes:
            filt = " AND mes=? "
            params.append(f"{int(mes):02d}")
        sql = f"""
            SELECT c.name AS categoria, v.tipo, v.total
            FROM {src} v
            JOIN categories c ON c.id=v.category_id
            WHERE v.company_id=? AND v.ano=? {filt}
            ORDER BY v.tipo, c.name
        """
        return self.q(sql, tuple(params))

# -----------------------------------------------------------------------------
# Helpers UI (ícones/mensagens) – igual
# -----------------------------------------------------------------------------
def std_icon(widget, sp): return widget.style().standardIcon(sp)
def msg_info(text, parent=None): QMessageBox.information(parent, APP_TITLE, text)
def msg_err(text, parent=None): QMessageBox.critical(parent, APP_TITLE, text)
def msg_yesno(text, parent=None):
    return QMessageBox.question(parent, APP_TITLE, text, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
def qdate_to_iso(qd: QDate) -> str:
    return f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"

def table_to_html(table: QTableWidget, title: str) -> str:
    head = "<tr>" + "".join(f"<th>{table.horizontalHeaderItem(c).text()}</th>" for c in range(table.columnCount())) + "</tr>"
    rows=[]
    for r in range(table.rowCount()):
        tds=[]
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
        import xlsxwriter  # opcional
        fn,_ = QFileDialog.getSaveFileName(parent,"Salvar Excel",f"{title}.xlsx","Excel (*.xlsx)")
        if not fn: return
        if not fn.lower().endswith(".xlsx"): fn += ".xlsx"
        wb = xlsxwriter.Workbook(fn); ws = wb.add_worksheet("Dados")
        for c in range(table.columnCount()): ws.write(0,c,table.horizontalHeaderItem(c).text())
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                it = table.item(r,c); ws.write(r+1,c, "" if it is None else it.text())
        wb.close(); msg_info(f"Planilha Excel gerada em:\n{fn}", parent)
    except Exception:
        fn,_ = QFileDialog.getSaveFileName(parent,"Salvar CSV (Excel)",f"{title}.csv","CSV (*.csv)")
        if not fn: return
        if not fn.lower().endswith(".csv"): fn += ".csv"
        with open(fn,"w",newline="",encoding="utf-8") as f:
            wr = csv.writer(f, delimiter=';')
            wr.writerow([table.horizontalHeaderItem(c).text() for c in range(table.columnCount())])
            for r in range(table.rowCount()):
                wr.writerow([(table.item(r,c).text() if table.item(r,c) else "") for c in range(table.columnCount())])
        msg_info(f"Arquivo CSV gerado em:\n{fn}", parent)

# -----------------------------------------------------------------------------
# Diálogos – **apenas** com chamadas a enable_autosize() e stretch_table()
# -----------------------------------------------------------------------------
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

class CompaniesDialog(QDialog):
    def __init__(self, db: DB, parent=None):
        super().__init__(parent); self.db=db
        self.setWindowTitle("Cadastro de Empresas")
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(["ID","CNPJ","Razão Social","Contato1","Contato2","Rua","Bairro","Nº","CEP","UF","Cidade","Email"])
        stretch_table(self.table)
        self.table.setItemDelegateForColumn(1, MaskDelegate(mask="00.000.000/0000-00", parent=self))
        self.table.setItemDelegateForColumn(8, MaskDelegate(mask="00000-000", parent=self))
        self.table.setItemDelegateForColumn(9, MaskDelegate(regex=r"[A-Za-z]{0,2}", uppercase=True, parent=self))

        btAdd = QPushButton("Novo"); btAdd.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        btSave = QPushButton("Salvar"); btSave.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btDel = QPushButton("Excluir"); btDel.setIcon(std_icon(self, self.style().SP_TrashIcon))
        btReload = QPushButton("Recarregar"); btReload.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btAdd.clicked.connect(self.add); btSave.clicked.connect(self.save)
        btDel.clicked.connect(self.delete); btReload.clicked.connect(self.load)
        lay = QVBoxLayout(self); lay.addWidget(self.table)
        hl = QHBoxLayout(); [hl.addWidget(b) for b in (btAdd,btSave,btDel,btReload)]; lay.addLayout(hl)
        self.load()
        enable_autosize(self, 0.8, 0.75, 1000, 650)

    # (demais métodos iguais aos anteriores)
    def load(self):
        rows = self.db.companies_all()
        self.table.setRowCount(0)
        for r in rows:
            row=self.table.rowCount(); self.table.insertRow(row)
            data=[r["id"], format_cnpj(r["cnpj"] or ""), r["razao_social"], r["contato1"], r["contato2"],
                  r["rua"], r["bairro"], r["numero"], r["cep"], (r["uf"] or ""), r["cidade"], r["email"]]
            for c,val in enumerate(data):
                it=QTableWidgetItem("" if val is None else str(val))
                if c==0: it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row,c,it)

    def add(self):
        r=self.table.rowCount(); self.table.insertRow(r); self.table.setItem(r,0,QTableWidgetItem(""))

    def save(self):
        for r in range(self.table.rowCount()):
            id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
            cnpj=self.table.item(r,1).text() if self.table.item(r,1) else ""
            cep =self.table.item(r,8).text() if self.table.item(r,8) else ""
            uf  =self.table.item(r,9).text().upper() if self.table.item(r,9) else ""
            if cnpj and not validate_cnpj(cnpj): msg_err(f"CNPJ inválido na linha {r+1}."); return
            if cep and not validate_cep(cep):   msg_err(f"CEP inválido na linha {r+1}."); return
            if uf and not validate_uf(uf):      msg_err(f"UF inválida na linha {r+1}."); return
            rec=dict(cnpj=only_digits(cnpj),
                     razao=self.table.item(r,2).text() if self.table.item(r,2) else "",
                     contato1=self.table.item(r,3).text() if self.table.item(r,3) else "",
                     contato2=self.table.item(r,4).text() if self.table.item(r,4) else "",
                     rua=self.table.item(r,5).text() if self.table.item(r,5) else "",
                     bairro=self.table.item(r,6).text() if self.table.item(r,6) else "",
                     numero=self.table.item(r,7).text() if self.table.item(r,7) else "",
                     cep=only_digits(cep), uf=uf,
                     cidade=self.table.item(r,10).text() if self.table.item(r,10) else "",
                     email=self.table.item(r,11).text() if self.table.item(r,11) else "", active=1)
            if not rec["razao"]: msg_err("Razão social é obrigatória."); return
            cid=int(id_txt) if id_txt.strip().isdigit() else None
            cid=self.db.company_save(rec, cid); self.table.setItem(r,0,QTableWidgetItem(str(cid)))
        msg_info("Registros salvos."); self.load()

    def delete(self):
        r=self.table.currentRow()
        if r<0: return
        id_txt=self.table.item(r,0).text() if self.table.item(r,0) else ""
        if not id_txt.strip().isdigit(): self.table.removeRow(r); return
        if not msg_yesno("Deseja excluir esta empresa?"): return
        auth=AdminAuthDialog(self.db,self)
        if not auth.exec_() or not auth.ok: return
        try: self.db.company_delete(int(id_txt))
        except sqlite3.IntegrityError as e: msg_err(f"Não foi possível excluir. Existem dependências.\n{e}"); return
        self.load()

class UsersDialog(QDialog):
    def __init__(self, db: DB, parent=None):
        super().__init__(parent); self.db=db
        self.setWindowTitle("Cadastro de Usuários")
        self.users = QComboBox(); self.users.currentIndexChanged.connect(self.load_user)
        self.edName = QLineEdit(); self.edUsername = QLineEdit()
        self.cbAdmin=QCheckBox("Administrador"); self.cbActive=QCheckBox("Ativo"); self.cbActive.setChecked(True)
        self.edNewPass=QLineEdit(); self.edNewPass.setEchoMode(QLineEdit.Password)
        self.boxEmp=QGroupBox("Acesso a empresas"); self.empChecks=[]; vemp=QVBoxLayout(self.boxEmp)
        for c in self.db.list_companies():
            chk=QCheckBox(f"{c['id']} - {c['razao_social']}"); chk.company_id=c["id"]; vemp.addWidget(chk); self.empChecks.append(chk)
        self.boxPerm=QGroupBox("Permissões"); self.permChecks={}; vperm=QVBoxLayout(self.boxPerm)
        for p in self.db.q("SELECT * FROM permission_types ORDER BY name"):
            chk=QCheckBox(f"{p['name']} ({p['code']})"); self.permChecks[p["code"]]=chk; vperm.addWidget(chk)
        btNovo=QPushButton("Novo"); btNovo.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        btSalvar=QPushButton("Salvar"); btSalvar.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btExcluir=QPushButton("Excluir"); btExcluir.setIcon(std_icon(self, self.style().SP_TrashIcon))
        btReset=QPushButton("Definir/Resetar Senha"); btReset.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btNovo.clicked.connect(self.new_user); btSalvar.clicked.connect(self.save_user)
        btExcluir.clicked.connect(self.delete_user); btReset.clicked.connect(self.reset_password)
        form=QFormLayout(); form.addRow("Usuários:", self.users); form.addRow("Nome:", self.edName)
        form.addRow("Login:", self.edUsername); form.addRow(self.cbAdmin); form.addRow(self.cbActive)
        form.addRow("Nova senha (novo usuário ou reset):", self.edNewPass)
        hl=QHBoxLayout(); hl.addWidget(self.boxEmp); hl.addWidget(self.boxPerm)
        lay=QVBoxLayout(self); lay.addLayout(form); lay.addLayout(hl)
        hl2=QHBoxLayout(); [hl2.addWidget(b) for b in (btNovo,btSalvar,btExcluir,btReset)]; lay.addLayout(hl2)
        self.populate()
        enable_autosize(self, 0.8, 0.75, 1000, 650)
    def populate(self):
        self.users.blockSignals(True)
        self.users.clear()
        self.users.addItem("-- novo --", 0)
        for u in self.db.users_all():
            self.users.addItem(f"{u['name']} ({u['username']})", u["id"])
        self.users.blockSignals(False)
        self.load_user(0)

    def load_user(self, idx):
        uid = self.users.currentData()
        self.edName.clear()
        self.edUsername.clear()
        self.cbAdmin.setChecked(False)
        self.cbActive.setChecked(True)
        for chk in self.empChecks:
            chk.setChecked(False)
        for chk in self.permChecks.values():
            chk.setChecked(False)
        if not uid:
            return
        u = self.db.q("SELECT * FROM users WHERE id=?", (uid,))[0]
        self.edName.setText(u["name"])
        self.edUsername.setText(u["username"])
        self.cbAdmin.setChecked(bool(u["is_admin"]))
        self.cbActive.setChecked(bool(u["active"]))
        acc = self.db.q("SELECT company_id FROM user_company_access WHERE user_id=?", (uid,))
        acc_ids = {r["company_id"] for r in acc}
        for chk in self.empChecks:
            chk.setChecked(chk.company_id in acc_ids)
        perms = self.db.user_permissions(uid)
        for code, chk in self.permChecks.items():
            chk.setChecked(perms.get(code, False))

    def new_user(self):
        self.users.setCurrentIndex(0)

    def collect(self):
        data = {
            "name": self.edName.text().strip(),
            "username": self.edUsername.text().strip(),
            "is_admin": self.cbAdmin.isChecked(),
            "active": self.cbActive.isChecked(),
            "password": self.edNewPass.text(),
            "companies": [],
            "perms": {}
        }
        for chk in self.empChecks:
            if chk.isChecked():
                data["companies"].append(chk.company_id)
        for code, chk in self.permChecks.items():
            data["perms"][code] = chk.isChecked()
        return data

    def save_user(self):
        data = self.collect()
        if not data["name"] or not data["username"]:
            msg_err("Nome e login são obrigatórios.", self)
            return
        if self.users.currentData() == 0 and not data["password"]:
            msg_err("Defina a senha do novo usuário.", self)
            return
        uid = self.users.currentData() or None
        uid = self.db.user_save(data, uid)
        msg_info("Usuário salvo.", self)
        self.populate()
        for i in range(self.users.count()):
            if self.users.itemData(i) == uid:
                self.users.setCurrentIndex(i)
                break

    def delete_user(self):
        uid = self.users.currentData()
        if not uid:
            return
        if not msg_yesno("Deseja excluir este usuário?", self):
            return
        self.db.user_delete(uid)
        msg_info("Usuário excluído.", self)
        self.populate()

    def reset_password(self):
        uid = self.users.currentData()
        if not uid:
            msg_err("Selecione um usuário existente.", self)
            return
        newp = self.edNewPass.text()
        if not newp:
            msg_err("Informe a nova senha.", self)
            return
        self.db.user_save(self.collect(), user_id=uid, reset_password=newp)
        msg_info("Senha redefinida.", self)

class BanksDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Cadastro de Bancos / Contas")
        self.table=QTableWidget(0,10)
        self.table.setHorizontalHeaderLabels(["ID","Banco","Nome da Conta","Tipo","Agência","Conta","Saldo Inicial","Saldo Atual","Ativo","Criado em"])
        stretch_table(self.table)
        btAdd=QPushButton("Novo"); btAdd.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        btSave=QPushButton("Salvar"); btSave.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btDel=QPushButton("Excluir"); btDel.setIcon(std_icon(self, self.style().SP_TrashIcon))
        btReload=QPushButton("Recarregar"); btReload.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btAdd.clicked.connect(self.add); btSave.clicked.connect(self.save)
        btDel.clicked.connect(self.delete); btReload.clicked.connect(self.load)
        lay=QVBoxLayout(self); lay.addWidget(self.table)
        hl=QHBoxLayout(); [hl.addWidget(b) for b in (btAdd,btSave,btDel,btReload)]; lay.addLayout(hl)
        self.load()
        enable_autosize(self, 0.7, 0.55, 900, 520)

    def load(self):
        rows = self.db.banks(self.company_id)
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            data = [
                r["id"], r["bank_name"], r["account_name"], r["account_type"], r["agency"], r["account_number"],
                r["initial_balance"], r["current_balance"], r["active"], r["created_at"]
            ]
            for c, val in enumerate(data):
                item = QTableWidgetItem("" if val is None else str(val))
                if c in (0, 9):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, c, item)

    def add(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))

    def save(self):
        for r in range(self.table.rowCount()):
            id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            rec = dict(
                bank_name=self.table.item(r, 1).text() if self.table.item(r, 1) else "",
                account_name=self.table.item(r, 2).text() if self.table.item(r, 2) else "",
                account_type=self.table.item(r, 3).text() if self.table.item(r, 3) else "",
                agency=self.table.item(r, 4).text() if self.table.item(r, 4) else "",
                account_number=self.table.item(r, 5).text() if self.table.item(r, 5) else "",
                initial_balance=float(self.table.item(r, 6).text() or 0),
                current_balance=float(self.table.item(r, 7).text() or 0),
                active=1 if (self.table.item(r, 8) and self.table.item(r, 8).text() not in ("0", "False", "false")) else 0
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
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Cadastro de Fornecedor / Cliente")
        self.table=QTableWidget(0,13)
        self.table.setHorizontalHeaderLabels(["ID","Tipo","CNPJ/CPF","Razão/Nome","Contato1","Contato2","Rua","Bairro","Nº","CEP","UF","Cidade","Email"])
        stretch_table(self.table)
        self.table.setItemDelegateForColumn(2, DocNumberDelegate(self))
        self.table.setItemDelegateForColumn(9, MaskDelegate(mask="00000-000", parent=self))
        self.table.setItemDelegateForColumn(10, MaskDelegate(regex=r"[A-Za-z]{0,2}", uppercase=True, parent=self))
        btAdd=QPushButton("Novo"); btAdd.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        btSave=QPushButton("Salvar"); btSave.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btDel=QPushButton("Excluir"); btDel.setIcon(std_icon(self, self.style().SP_TrashIcon))
        btReload=QPushButton("Recarregar"); btReload.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btAdd.clicked.connect(self.add); btSave.clicked.connect(self.save)
        btDel.clicked.connect(self.delete); btReload.clicked.connect(self.load)
        lay=QVBoxLayout(self); lay.addWidget(self.table)
        hl=QHBoxLayout(); [hl.addWidget(b) for b in (btAdd,btSave,btDel,btReload)]; lay.addLayout(hl)
        self.load()
        enable_autosize(self, 0.85, 0.75, 1100, 650)

    def load(self):
        rows = self.db.entities(self.company_id)
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            data = [
                r["id"], r["kind"], (r["cnpj_cpf"] or ""), r["razao_social"], r["contato1"], r["contato2"], r["rua"], r["bairro"],
                r["numero"], r["cep"], (r["uf"] or ""), r["cidade"], r["email"]
            ]
            # formata doc se vier só com dígitos
            d = only_digits(data[2])
            if len(d) == 11:
                data[2] = format_cpf(d)
            elif len(d) == 14:
                data[2] = format_cnpj(d)
            if data[9]:
                cepd = only_digits(data[9]); 
                if len(cepd) == 8:
                    data[9] = f"{cepd[:5]}-{cepd[5:]}"
            for c, val in enumerate(data):
                item = QTableWidgetItem("" if val is None else str(val))
                if c == 0:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, c, item)

    def add(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))
        self.table.setItem(r, 1, QTableWidgetItem("FORNECEDOR"))

    def save(self):
        for r in range(self.table.rowCount()):
            id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            doc = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            cep = self.table.item(r, 9).text() if self.table.item(r, 9) else ""
            uf  = self.table.item(r, 10).text().upper() if self.table.item(r, 10) else ""
            d = only_digits(doc)
            if d:
                if len(d) == 11 and not validate_cpf(d):
                    msg_err(f"CPF inválido na linha {r+1}.")
                    return
                if len(d) == 14 and not validate_cnpj(d):
                    msg_err(f"CNPJ inválido na linha {r+1}.")
                    return
                if len(d) not in (11,14):
                    msg_err(f"Documento inválido (CPF/CNPJ) na linha {r+1}.")
                    return
            if cep and not validate_cep(cep):
                msg_err(f"CEP inválido na linha {r+1}.")
                return
            if uf and not validate_uf(uf):
                msg_err(f"UF inválida na linha {r+1}.")
                return

            rec = dict(
                kind=self.table.item(r, 1).text() if self.table.item(r, 1) else "FORNECEDOR",
                cnpj_cpf=d,
                razao_social=self.table.item(r, 3).text() if self.table.item(r, 3) else "",
                contato1=self.table.item(r, 4).text() if self.table.item(r, 4) else "",
                contato2=self.table.item(r, 5).text() if self.table.item(r, 5) else "",
                rua=self.table.item(r, 6).text() if self.table.item(r, 6) else "",
                bairro=self.table.item(r, 7).text() if self.table.item(r, 7) else "",
                numero=self.table.item(r, 8).text() if self.table.item(r, 8) else "",
                cep=only_digits(cep),
                uf=uf,
                cidade=self.table.item(r, 11).text() if self.table.item(r, 11) else "",
                email=self.table.item(r, 12).text() if self.table.item(r, 12) else "",
                active=1
            )
            if not rec["razao_social"]:
                msg_err("Razão/Nome é obrigatório.")
                return
            eid = int(id_txt) if id_txt.strip().isdigit() else None
            eid = self.db.entity_save(self.company_id, rec, eid)
            self.table.setItem(r, 0, QTableWidgetItem(str(eid)))
        msg_info("Registros salvos.")
        self.load()

    def delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
        if not id_txt.strip().isdigit():
            self.table.removeRow(r)
            return
        if not msg_yesno("Excluir este cadastro?"):
            return
        try:
            self.db.entity_delete(int(id_txt))
        except sqlite3.IntegrityError as e:
            msg_err(f"Não foi possível excluir. Existem lançamentos vinculados.\n{e}")
            return
        self.load()

class CategoriesDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Categorias / Subcategorias")
        self.cbTipo=QComboBox(); self.cbTipo.addItems(["PAGAR","RECEBER"]); self.cbTipo.currentIndexChanged.connect(self.load)
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(["ID Cat","Categoria","ID Sub","Subcategoria"])
        stretch_table(self.table)
        btAddCat=QPushButton("Nova Categoria"); btAddCat.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        btAddSub=QPushButton("Nova Subcategoria"); btAddSub.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        btSave=QPushButton("Salvar"); btSave.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btDel=QPushButton("Excluir Selecionado"); btDel.setIcon(std_icon(self, self.style().SP_TrashIcon))
        btReload=QPushButton("Recarregar"); btReload.setIcon(std_icon(self, self.style().SP_BrowserReload))
        btAddCat.clicked.connect(self.add_cat); btAddSub.clicked.connect(self.add_sub)
        btSave.clicked.connect(self.save); btDel.clicked.connect(self.delete); btReload.clicked.connect(self.load)
        top=QHBoxLayout(); top.addWidget(QLabel("Tipo:")); top.addWidget(self.cbTipo); top.addStretch()
        lay=QVBoxLayout(self); lay.addLayout(top); lay.addWidget(self.table)
        hl=QHBoxLayout(); [hl.addWidget(b) for b in (btAddCat,btAddSub,btSave,btDel,btReload)]; lay.addLayout(hl)
        self.load()
        enable_autosize(self, 0.75, 0.6, 950, 560)

    def load(self):
        self.table.setRowCount(0)
        cats = self.db.categories(self.company_id, self.cbTipo.currentText())
        for c in cats:
            subs = self.db.subcategories(c["id"])
            if not subs:
                row = self.table.rowCount()
                self.table.insertRow(row)
                vals = [c["id"], c["name"], "", ""]
                for col, val in enumerate(vals):
                    it = QTableWidgetItem(str(val) if val is not None else "")
                    if col in (0, 2):
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, col, it)
            else:
                for s in subs:
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    vals = [c["id"], c["name"], s["id"], s["name"]]
                    for col, val in enumerate(vals):
                        it = QTableWidgetItem(str(val))
                        if col in (0, 2):
                            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, col, it)

    def add_cat(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))
        self.table.setItem(r, 1, QTableWidgetItem("NOVA CATEGORIA"))
        self.table.setItem(r, 2, QTableWidgetItem(""))
        self.table.setItem(r, 3, QTableWidgetItem(""))

    def add_sub(self):
        r = self.table.currentRow()
        if r < 0:
            msg_err("Selecione uma linha com categoria para adicionar subcategoria.")
            return
        cat_id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
        if not cat_id_txt.strip().isdigit():
            msg_err("Salve a categoria antes.")
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(cat_id_txt))
        self.table.setItem(row, 1, QTableWidgetItem(self.table.item(r, 1).text()))
        self.table.setItem(row, 2, QTableWidgetItem(""))
        self.table.setItem(row, 3, QTableWidgetItem("NOVA SUB"))

    def save(self):
        for r in range(self.table.rowCount()):
            cat_id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            cat_name = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            sub_id_txt = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            sub_name = self.table.item(r, 3).text() if self.table.item(r, 3) else ""
            if not cat_name:
                msg_err("Categoria sem nome.")
                return
            if cat_id_txt.strip().isdigit():
                cat_id = int(cat_id_txt)
            else:
                cat_id = self.db.category_save(self.company_id, cat_name, self.cbTipo.currentText(), None)
                self.table.setItem(r, 0, QTableWidgetItem(str(cat_id)))
            if sub_name and not sub_id_txt.strip().isdigit():
                sid = self.db.subcategory_save(cat_id, sub_name, None)
                self.table.setItem(r, 2, QTableWidgetItem(str(sid)))
            elif sub_id_txt.strip().isdigit():
                self.db.subcategory_save(int(cat_id), sub_name, int(sub_id_txt))
        msg_info("Categorias salvas.")
        self.load()

    def delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        cat_id_txt = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
        sub_id_txt = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
        if sub_id_txt.strip().isdigit():
            if not msg_yesno("Excluir a subcategoria selecionada?"):
                return
            try:
                self.db.subcategory_delete(int(sub_id_txt))
            except sqlite3.IntegrityError as e:
                msg_err(f"Não foi possível excluir.\n{e}")
                return
        elif cat_id_txt.strip().isdigit():
            if not msg_yesno("Excluir a categoria e suas subcategorias?"):
                return
            try:
                self.db.category_delete(int(cat_id_txt))
            except sqlite3.IntegrityError as e:
                msg_err(f"Não foi possível excluir.\n{e}")
                return
        self.load()

class PaymentDialog(QDialog):
    def __init__(self, db: DB, company_id, tx, user_id, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id; self.tx=tx; self.user_id=user_id
        self.setWindowTitle("Liquidar Lançamento")
        form=QFormLayout(self)
        self.dt=QDateEdit(QDate.currentDate()); self.dt.setCalendarPopup(True)
        self.cbBank=QComboBox()
        for b in self.db.banks(company_id):
            self.cbBank.addItem(f"{b['bank_name']} - {b['account_name'] or ''}", b["id"])
        faltante=max(0.0, float(tx["valor"]) - float(tx["pago"]))
        self.edValor=QLineEdit(f"{faltante:.2f}"); self.edJuros=QLineEdit("0"); self.edDesc=QLineEdit("0"); self.edDoc=QLineEdit()
        form.addRow("Data pagamento:", self.dt); form.addRow("Banco:", self.cbBank); form.addRow("Valor:", self.edValor)
        form.addRow("Juros:", self.edJuros); form.addRow("Desconto:", self.edDesc); form.addRow("Documento ref.:", self.edDoc)
        bt=QPushButton("Confirmar"); bt.setIcon(std_icon(self, self.style().SP_DialogApplyButton)); bt.clicked.connect(self.ok)
        form.addRow(bt); self.ok_clicked=False
        enable_autosize(self, 0.45, 0.4, 520, 360)

    def ok(self):
        try:
            rec = dict(
                transaction_id=self.tx["id"],
                company_id=self.company_id,
                payment_date=qdate_to_iso(self.dt.date()),
                bank_id=self.cbBank.currentData(),
                amount=float(self.edValor.text().replace(",", ".")),
                interest=float(self.edJuros.text().replace(",", ".")),
                discount=float(self.edDesc.text().replace(",", ".")),
                doc_ref=self.edDoc.text(),
                created_by=self.user_id
            )
            self.db.payment_add(rec)
            self.ok_clicked = True
            self.accept()
        except sqlite3.IntegrityError as e:
            msg_err(str(e), self)

class TransactionsDialog(QDialog):
    def __init__(self, db: DB, company_id: int, user_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id; self.user_id=user_id
        self.setWindowTitle("Lançamentos - Contas a Pagar / Receber")
        self.rbPagar=QRadioButton("Contas a Pagar"); self.rbReceber=QRadioButton("Contas a Receber")
        self.rbPagar.setChecked(True); self.rbPagar.toggled.connect(self.load)
        top=QHBoxLayout(); top.addWidget(self.rbPagar); top.addWidget(self.rbReceber); top.addStretch()
        self.cbEnt=QComboBox(); self.cbCat=QComboBox(); self.cbSub=QComboBox()
        self.cbForma=QComboBox(); self.cbForma.addItems(["Boleto","PIX","Transferência","Dinheiro"])
        self.cbBanco=QComboBox()
        self.dtLanc=QDateEdit(QDate.currentDate()); self.dtLanc.setCalendarPopup(True)
        self.dtVenc=QDateEdit(QDate.currentDate()); self.dtVenc.setCalendarPopup(True)
        self.edDesc=QLineEdit(); self.edValor=QLineEdit()
        self.spParcelas=QSpinBox(); self.spParcelas.setRange(1,120); self.spParcelas.setValue(1)
        form=QFormLayout()
        for label, w in [("Fornecedor/Cliente:",self.cbEnt),("Categoria:",self.cbCat),("Subcategoria:",self.cbSub),
                         ("Descrição:",self.edDesc),("Data Lanç.:",self.dtLanc),("Data Venc.:",self.dtVenc),
                         ("Forma Pagto:",self.cbForma),("Qtd Parcelas:",self.spParcelas),
                         ("Banco padr.:",self.cbBanco),("Valor (total):",self.edValor)]:
            form.addRow(label, w)

        self.table=QTableWidget(0,10)
        self.table.setHorizontalHeaderLabels(["ID","Tipo","Entidade","Categoria","Subcat","Descrição","Lançamento","Vencimento","Valor","Status/Pago"])
        stretch_table(self.table)

        btNovo=QPushButton("Novo"); btNovo.setIcon(std_icon(self, self.style().SP_FileDialogNewFolder))
        btSalvar=QPushButton("Salvar"); btSalvar.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btExcluir=QPushButton("Excluir"); btExcluir.setIcon(std_icon(self, self.style().SP_TrashIcon))
        btLiquidar=QPushButton("Liquidar"); btLiquidar.setIcon(std_icon(self, self.style().SP_DialogApplyButton))
        btEstornar=QPushButton("Estornar baixa"); btEstornar.setIcon(std_icon(self, self.style().SP_ArrowBack))
        btExpPdf=QPushButton("PDF da lista"); btExpPdf.setIcon(std_icon(self, self.style().SP_DriveDVDIcon))
        btExpXls=QPushButton("Excel da lista"); btExpXls.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btNovo.clicked.connect(self.new); btSalvar.clicked.connect(self.save); btExcluir.clicked.connect(self.delete)
        btLiquidar.clicked.connect(self.liquidar); btEstornar.clicked.connect(self.estornar)
        btExpPdf.clicked.connect(lambda: export_pdf_from_table(self,self.table,"Lancamentos"))
        btExpXls.clicked.connect(lambda: export_excel_from_table(self,self.table,"Lancamentos"))

        lay=QVBoxLayout(self); lay.addLayout(top); lay.addLayout(form); lay.addWidget(self.table)
        hl=QHBoxLayout(); [hl.addWidget(b) for b in (btNovo,btSalvar,btExcluir,btLiquidar,btEstornar,btExpPdf,btExpXls)]; lay.addLayout(hl)

        self.populate_static(); self.load()
        enable_autosize(self, 0.9, 0.85, 1200, 720)

    def tipo(self):
        return "PAGAR" if self.rbPagar.isChecked() else "RECEBER"

    def populate_static(self):
        self.cbBanco.clear()
        for b in self.db.banks(self.company_id):
            self.cbBanco.addItem(f"{b['bank_name']} - {b['account_name'] or ''}", b["id"])
        self.reload_cats_ents()

    def reload_cats_ents(self):
        self.cbEnt.clear()
        kind = "FORNECEDOR" if self.tipo() == "PAGAR" else "CLIENTE"
        for e in self.db.entities(self.company_id, kind):
            self.cbEnt.addItem(e["razao_social"], e["id"])
        self.cbCat.clear()
        for c in self.db.categories(self.company_id, self.tipo()):
            self.cbCat.addItem(c["name"], c["id"])
        self.cbCat.currentIndexChanged.connect(self.reload_subs)
        self.reload_subs()

    def reload_subs(self):
        self.cbSub.clear()
        cat_id = self.cbCat.currentData()
        if not cat_id:
            return
        for s in self.db.subcategories(cat_id):
            self.cbSub.addItem(s["name"], s["id"])

    def load(self):
        self.reload_cats_ents()
        rows = self.db.transactions(self.company_id, self.tipo())
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            ent = self.db.q("SELECT razao_social FROM entities WHERE id=?", (r["entity_id"],))
            cat = self.db.q("SELECT name FROM categories WHERE id=?", (r["category_id"],))
            sub = self.db.q("SELECT name FROM subcategories WHERE id=?", (r["subcategory_id"],))
            ent_name = ent[0]["razao_social"] if ent else ""
            cat_name = cat[0]["name"] if cat else ""
            sub_name = sub[0]["name"] if sub else ""
            data = [
                r["id"], r["tipo"], ent_name, cat_name, sub_name, r["descricao"], r["data_lanc"],
                r["data_venc"], f"{r['valor']:.2f}", f"{r['status']} / pago {r['pago']:.2f}"
            ]
            for c, val in enumerate(data):
                it = QTableWidgetItem("" if val is None else str(val))
                if c == 0:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, c, it)

    def new(self):
        self.edDesc.clear(); self.edValor.clear()
        self.spParcelas.setValue(1)
        self.dtLanc.setDate(QDate.currentDate())
        self.dtVenc.setDate(QDate.currentDate())

    def save(self):
        try:
            valor = float(self.edValor.text().replace(",", "."))
        except ValueError:
            msg_err("Valor inválido.")
            return
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
            valor=valor,
            banco_id_padrao=self.cbBanco.currentData(),
            created_by=self.user_id
        )
        try:
            self.db.transaction_save(rec, None)
        except sqlite3.IntegrityError as e:
            msg_err(str(e))
            return
        msg_info("Lançamento salvo.")
        self.load()

    def current_tx(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        tx_id = int(self.table.item(r, 0).text())
        sql = """SELECT t.*,
                        IFNULL((SELECT SUM(p.amount+p.interest-p.discount) FROM payments p
                                WHERE p.transaction_id=t.id),0) AS pago
                 FROM transactions t WHERE t.id=?"""
        return self.db.q(sql, (tx_id,))[0]

    def delete(self):
        tx = self.current_tx()
        if not tx:
            return
        if not msg_yesno("Excluir este lançamento?"):
            return
        try:
            self.db.transaction_delete(tx["id"])
        except sqlite3.IntegrityError as e:
            msg_err(str(e))
            return
        self.load()

    def liquidar(self):
        tx = self.current_tx()
        if not tx:
            msg_err("Selecione um lançamento.")
            return
        dlg = PaymentDialog(self.db, self.company_id, tx, self.user_id, self)
        if dlg.exec_() and dlg.ok_clicked:
            msg_info("Baixa registrada.")
            self.load()

    def estornar(self):
        tx = self.current_tx()
        if not tx:
            return
        pays = self.db.payments_for(tx["id"])
        if not pays:
            msg_err("Não há baixas para estornar.")
            return
        last_id = pays[-1]["id"]
        if not msg_yesno(f"Estornar a última baixa (ID {last_id})?"):
            return
        try:
            self.db.payment_delete(last_id)
        except sqlite3.IntegrityError as e:
            msg_err(str(e))
            return
        self.load()

class CashflowDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Fluxo de Caixa")
        self.dtIni=QDateEdit(QDate.currentDate().addMonths(-1)); self.dtIni.setCalendarPopup(True)
        self.dtFim=QDateEdit(QDate.currentDate()); self.dtFim.setCalendarPopup(True)
        self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(["Data","Conta","Valor (efeito)"])
        stretch_table(self.table)
        self.lbTotal=QLabel("Total: 0,00")
        bt=QPushButton("Atualizar"); bt.setIcon(std_icon(self, self.style().SP_BrowserReload)); bt.clicked.connect(self.load)
        btPdf=QPushButton("Exportar PDF"); btPdf.setIcon(std_icon(self, self.style().SP_DriveDVDIcon))
        btCsv=QPushButton("Exportar Excel/CSV"); btCsv.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btPdf.clicked.connect(lambda: export_pdf_from_table(self,self.table,"Fluxo_de_Caixa"))
        btCsv.clicked.connect(lambda: export_excel_from_table(self,self.table,"Fluxo_de_Caixa"))
        form=QHBoxLayout(); form.addWidget(QLabel("Início:")); form.addWidget(self.dtIni)
        form.addWidget(QLabel("Fim:")); form.addWidget(self.dtFim); form.addWidget(bt); form.addStretch()
        lay=QVBoxLayout(self); lay.addLayout(form); lay.addWidget(self.table); lay.addWidget(self.lbTotal)
        hl=QHBoxLayout(); hl.addWidget(btPdf); hl.addWidget(btCsv); hl.addStretch(); lay.addLayout(hl)
        self.load()
        enable_autosize(self, 0.8, 0.7, 1050, 600)

    def load(self):
        sql = """SELECT data, bank_name||' - '||IFNULL(account_name,'') AS conta, valor_efeito
                 FROM vw_fluxo_caixa
                 WHERE company_id=? AND date(data) BETWEEN date(?) AND date(?)
                 ORDER BY date(data)"""
        params = (self.company_id, qdate_to_iso(self.dtIni.date()), qdate_to_iso(self.dtFim.date()))
        rows = self.db.q(sql, params)
        self.table.setRowCount(0)
        total = 0.0
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            total += float(r["valor_efeito"])
            self.table.setItem(row, 0, QTableWidgetItem(r["data"]))
            conta = f"{r['conta']}"
            self.table.setItem(row, 1, QTableWidgetItem(conta))
            self.table.setItem(row, 2, QTableWidgetItem(f"{float(r['valor_efeito']):.2f}"))
        self.lbTotal.setText(f"Total: {total:.2f}")

class DREDialog(QDialog):
    def __init__(self, db: DB, company_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id
        self.setWindowTitle("Demonstração de Resultado (DRE)")
        self.spAno=QSpinBox(); self.spAno.setRange(2000,2099); self.spAno.setValue(date.today().year)
        self.spMes=QSpinBox(); self.spMes.setRange(0,12); self.spMes.setValue(0)
        self.cbReg=QComboBox(); self.cbReg.addItems(["COMPETENCIA","CAIXA"])
        bt=QPushButton("Gerar"); bt.setIcon(std_icon(self, self.style().SP_BrowserReload)); bt.clicked.connect(self.load)
        btPdf=QPushButton("Exportar PDF"); btPdf.setIcon(std_icon(self, self.style().SP_DriveDVDIcon))
        btCsv=QPushButton("Exportar Excel/CSV"); btCsv.setIcon(std_icon(self, self.style().SP_DialogSaveButton))
        btPdf.clicked.connect(lambda: export_pdf_from_table(self,self.table,"DRE"))
        btCsv.clicked.connect(lambda: export_excel_from_table(self,self.table,"DRE"))
        top=QHBoxLayout(); 
        for w in [QLabel("Ano:"), self.spAno, QLabel("Mês (0=todos):"), self.spMes, QLabel("Regime:"), self.cbReg, bt]:
            top.addWidget(w)
        top.addStretch()
        self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(["Categoria","Tipo","Valor"])
        stretch_table(self.table)
        self.lbResumo=QLabel("")
        lay=QVBoxLayout(self); lay.addLayout(top); lay.addWidget(self.table); lay.addWidget(self.lbResumo)
        hl=QHBoxLayout(); hl.addWidget(btPdf); hl.addWidget(btCsv); hl.addStretch(); lay.addLayout(hl)
        enable_autosize(self, 0.8, 0.7, 1050, 600)

    def load(self):
        mes = self.spMes.value() or None
        rows = self.db.dre(self.company_id, self.spAno.value(), mes, self.cbReg.currentText())
        self.table.setRowCount(0)
        rec = 0.0; desp = 0.0
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r["categoria"]))
            self.table.setItem(row, 1, QTableWidgetItem(r["tipo"]))
            val = float(r["total"])
            self.table.setItem(row, 2, QTableWidgetItem(f"{val:.2f}"))
            if r["tipo"] == "RECEBER":
                rec += val
            else:
                desp += val
        margem = rec - abs(desp)
        perc = (margem / rec * 100) if rec else 0
        self.lbResumo.setText(f"Receitas: {rec:.2f} | Despesas: {abs(desp):.2f} | Margem: {margem:.2f} ({perc:.1f}%)")

class PeriodDialog(QDialog):
    def __init__(self, db: DB, company_id: int, user_id: int, parent=None):
        super().__init__(parent); self.db=db; self.company_id=company_id; self.user_id=user_id
        self.setWindowTitle("Fechamento de Mês")
        self.spAno=QSpinBox(); self.spAno.setRange(2000,2099); self.spAno.setValue(date.today().year)
        self.spMes=QSpinBox(); self.spMes.setRange(1,12); self.spMes.setValue(date.today().month)
        self.lbStatus=QLabel("Status: -")
        btStatus=QPushButton("Ver status"); btStatus.setIcon(std_icon(self, self.style().SP_MessageBoxInformation)); btStatus.clicked.connect(self.check)
        btFechar=QPushButton("Fechar mês"); btFechar.setIcon(std_icon(self, self.style().SP_DialogApplyButton)); btFechar.clicked.connect(lambda: self.set_status('CLOSED'))
        btReabrir=QPushButton("Reabrir mês"); btReabrir.setIcon(std_icon(self, self.style().SP_DialogResetButton)); btReabrir.clicked.connect(lambda: self.set_status('OPEN'))
        form=QFormLayout(self); form.addRow("Ano:", self.spAno); form.addRow("Mês:", self.spMes); form.addRow(self.lbStatus)
        hl=QHBoxLayout(); [hl.addWidget(b) for b in (btStatus,btFechar,btReabrir)]; form.addRow(hl)
        self.check()
        enable_autosize(self, 0.5, 0.45, 560, 380)

    def check(self):
        st = self.db.period_status(self.company_id, self.spMes.value(), self.spAno.value())
        self.lbStatus.setText(f"Status: {st}")

    def set_status(self, status):
        self.db.period_set(self.company_id, self.spMes.value(), self.spAno.value(), status, self.user_id)
        msg_info(f"Mês marcado como {status}.")
        self.check()

# -----------------------------------------------------------------------------
# Login / MainWindow
# -----------------------------------------------------------------------------
class LoginWindow(QWidget):
    def __init__(self, db: DB):
        super().__init__(); self.db=db
        self.setWindowTitle(f"{APP_TITLE} - Login")
        self.cbEmp=QComboBox()
        for c in self.db.list_companies(): self.cbEmp.addItem(c["razao_social"], c["id"])
        self.cbUser=QComboBox(); self.cbEmp.currentIndexChanged.connect(self.reload_users)
        self.edPass=QLineEdit(); self.edPass.setEchoMode(QLineEdit.Password)
        self.btEntrar=QPushButton("Entrar"); self.btEntrar.setIcon(std_icon(self, self.style().SP_DialogOkButton))
        self.btEntrar.clicked.connect(self.login)
        self.btEmp=QPushButton("Cadastro de empresa"); self.btEmp.setIcon(std_icon(self, self.style().SP_ComputerIcon))
        self.btUser=QPushButton("Cadastro de usuário"); self.btUser.setIcon(std_icon(self, self.style().SP_DirHomeIcon))
        self.btEmp.clicked.connect(self.open_emp_admin); self.btUser.clicked.connect(self.open_user_admin)
        form=QFormLayout(); form.addRow("Empresa:", self.cbEmp); form.addRow("Usuário:", self.cbUser); form.addRow("Senha:", self.edPass)
        hl=QHBoxLayout(); hl.addWidget(self.btEmp); hl.addWidget(self.btUser); hl.addStretch()
        lay=QVBoxLayout(self); lay.addLayout(form); lay.addWidget(self.btEntrar); lay.addLayout(hl)
        self.reload_users()
        enable_autosize(self, 0.45, 0.4, 520, 360)

    def reload_users(self):
        self.cbUser.clear()
        for u in self.db.list_users_for_company(self.cbEmp.currentData()):
            self.cbUser.addItem(f"{u['name']} ({u['username']})", u["username"])

    def open_emp_admin(self):
        auth=AdminAuthDialog(self.db,self)
        if auth.exec_() and auth.ok:
            CompaniesDialog(self.db,self).exec_()
            self.cbEmp.clear()
            for c in self.db.list_companies(): self.cbEmp.addItem(c["razao_social"], c["id"])
            self.reload_users()

    def open_user_admin(self):
        auth=AdminAuthDialog(self.db,self)
        if auth.exec_() and auth.ok:
            UsersDialog(self.db,self).exec_()
            self.reload_users()

    def login(self):
        company_id=self.cbEmp.currentData(); username=self.cbUser.currentData()
        user=self.db.verify_login(company_id, username, self.edPass.text())
        if not user: msg_err("Login inválido ou sem acesso à empresa."); return
        self.hide(); self.main=MainWindow(self.db, company_id, user); self.main.show()

class MainWindow(QMainWindow):
    def __init__(self, db: DB, company_id: int, user_row: sqlite3.Row):
        super().__init__(); self.db=db; self.company_id=company_id; self.user=user_row
        comp=self.db.q("SELECT razao_social FROM companies WHERE id=?", (company_id,))[0]["razao_social"]
        self.setWindowTitle(f"{APP_TITLE} - {comp}")
        menubar=self.menuBar()
        mCad=menubar.addMenu("Cadastros")
        actBanks=QAction("Bancos", self); actBanks.triggered.connect(self.open_banks)
        actEnts=QAction("Fornecedores/Clientes", self); actEnts.triggered.connect(self.open_entities)
        actCats=QAction("Categorias/Subcategorias", self); actCats.triggered.connect(self.open_categories)
        mCad.addAction(actBanks); mCad.addAction(actEnts); mCad.addAction(actCats)
        if self.db.is_admin(self.user["id"]):
            actEmp=QAction("Empresas (admin)", self); actEmp.triggered.connect(self.open_companies); mCad.addAction(actEmp)
            actUsers=QAction("Usuários (admin)", self); actUsers.triggered.connect(self.open_users); mCad.addAction(actUsers)
        mMov=menubar.addMenu("Movimentação"); actTx=QAction("Lançamentos (Pagar/Receber)", self); actTx.triggered.connect(self.open_transactions); mMov.addAction(actTx)
        mRel=menubar.addMenu("Relatórios"); actFluxo=QAction("Fluxo de Caixa", self); actFluxo.triggered.connect(self.open_cashflow)
        actDre=QAction("DRE", self); actDre.triggered.connect(self.open_dre); mRel.addAction(actFluxo); mRel.addAction(actDre)
        mPer=menubar.addMenu("Período"); actPer=QAction("Fechar / Reabrir Mês", self); actPer.triggered.connect(self.open_period); mPer.addAction(actPer)
        actSair=QAction("Sair", self); actSair.triggered.connect(self.close); menubar.addAction(actSair)
        w=QWidget(); lay=QVBoxLayout(w)
        lay.addWidget(QLabel(f"Usuário: {self.user['name']} ({'ADMIN' if self.user['is_admin'] else 'Usuário'})"))
        lay.addWidget(QLabel(f"Empresa corrente: {comp}"))
        self.setCentralWidget(w)
        enable_autosize(self, 0.95, 0.9, 1280, 740)

    def open_companies(self): CompaniesDialog(self.db, self).exec_()
    def open_users(self): UsersDialog(self.db, self).exec_()
    def open_banks(self): BanksDialog(self.db, self.company_id, self).exec_()
    def open_entities(self): EntitiesDialog(self.db, self.company_id, self).exec_()
    def open_categories(self): CategoriesDialog(self.db, self.company_id, self).exec_()
    def open_transactions(self): TransactionsDialog(self.db, self.company_id, self.user["id"], self).exec_()
    def open_cashflow(self): CashflowDialog(self.db, self.company_id, self).exec_()
    def open_dre(self): DREDialog(self.db, self.company_id, self).exec_()
    def open_period(self): PeriodDialog(self.db, self.company_id, self.user["id"], self).exec_()

# -----------------------------------------------------------------------------
def main():
    conn = ensure_db(); db = DB(conn)
    app = QApplication(sys.argv)
    login = LoginWindow(db); login.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
