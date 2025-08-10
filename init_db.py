# init_db.py
# -----------------------------------------------------------------------------
# Cria o banco SQLite "erp_financeiro.db" com todo o esquema necessário
# para o Sistema de Gestão Financeira (multi-empresa, ACL, lançamentos,
# liquidações, fluxo de caixa, DRE, fechamento de mês).
# -----------------------------------------------------------------------------

import os
import sqlite3
import binascii
import os as _os
from datetime import datetime
from pathlib import Path
import hashlib

DB_FILE = "erp_financeiro.db"
SCHEMA_VERSION = 1

# -------- utilitários de senha (PBKDF2-HMAC-SHA256) --------------------------
def hash_password(plain: str, *, iterations: int = 240_000) -> tuple[bytes, bytes, int]:
    """
    Retorna (salt, hash, iterations). Armazene os 3 na tabela users.
    """
    salt = _os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return salt, dk, iterations

def verify_password(plain: str, salt: bytes, pw_hash: bytes, iterations: int) -> bool:
    calc = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return hashlib.compare_digest(calc, pw_hash)

# --------- SQL do esquema ----------------------------------------------------
SCHEMA_SQL = f"""
PRAGMA foreign_keys = ON;

-- Metadados de versão do esquema
CREATE TABLE IF NOT EXISTS app_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Empresas
CREATE TABLE IF NOT EXISTS companies (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  cnpj          TEXT UNIQUE,
  razao_social  TEXT NOT NULL,
  contato1      TEXT,
  contato2      TEXT,
  rua           TEXT, bairro TEXT, numero TEXT, cep TEXT,
  uf            TEXT CHECK (uf IS NULL OR length(uf)=2),
  cidade        TEXT,
  email         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  active        INTEGER NOT NULL DEFAULT 1
);

-- Usuários
CREATE TABLE IF NOT EXISTS users (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL,
  username       TEXT NOT NULL UNIQUE,
  password_salt  BLOB NOT NULL,
  password_hash  BLOB NOT NULL,
  iterations     INTEGER NOT NULL,
  is_admin       INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  active         INTEGER NOT NULL DEFAULT 1
);

-- Acesso de usuários às empresas (checklist "Acesso a empresas")
CREATE TABLE IF NOT EXISTS user_company_access (
  user_id     INTEGER NOT NULL,
  company_id  INTEGER NOT NULL,
  PRIMARY KEY (user_id, company_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- Tipos de permissão (checkboxes dos módulos)
CREATE TABLE IF NOT EXISTS permission_types (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  code        TEXT NOT NULL UNIQUE,   -- e.g., CONTAS, BANCOS, FORNECEDOR_CLIENTE, NFE, DRE
  name        TEXT NOT NULL,
  description TEXT
);

-- Permissões por usuário
CREATE TABLE IF NOT EXISTS user_permissions (
  user_id  INTEGER NOT NULL,
  perm_id  INTEGER NOT NULL,
  allowed  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, perm_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (perm_id) REFERENCES permission_types(id) ON DELETE CASCADE
);

-- Contas bancárias (Cadastro de Bancos)
CREATE TABLE IF NOT EXISTS bank_accounts (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id       INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  bank_name        TEXT NOT NULL,     -- "CAIXA", "Banco do Brasil", etc.
  account_name     TEXT,              -- "Caixa", "Conta Corrente Operacional"
  account_type     TEXT,              -- "CAIXA", "CC", "POUPANCA"
  agency           TEXT,
  account_number   TEXT,
  initial_balance  REAL NOT NULL DEFAULT 0.0,
  current_balance  REAL NOT NULL DEFAULT 0.0,
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  active           INTEGER NOT NULL DEFAULT 1
);

-- Fornecedores / Clientes
CREATE TABLE IF NOT EXISTS entities (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id    INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK (kind IN ('FORNECEDOR','CLIENTE','AMBOS')),
  cnpj_cpf      TEXT,
  razao_social  TEXT NOT NULL,
  contato1      TEXT,
  contato2      TEXT,
  rua           TEXT, bairro TEXT, numero TEXT, cep TEXT,
  uf            TEXT, cidade TEXT,
  email         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  active        INTEGER NOT NULL DEFAULT 1
);

-- Categorias e Subcategorias (para títulos)
CREATE TABLE IF NOT EXISTS categories (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  tipo        TEXT NOT NULL CHECK (tipo IN ('PAGAR','RECEBER')),
  UNIQUE(company_id, name, tipo)
);

CREATE TABLE IF NOT EXISTS subcategories (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id   INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  UNIQUE(category_id, name)
);

-- Lançamentos (Contas a Pagar / Receber)
CREATE TABLE IF NOT EXISTS transactions (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id       INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  tipo             TEXT NOT NULL CHECK (tipo IN ('PAGAR','RECEBER')),
  entity_id        INTEGER REFERENCES entities(id),
  category_id      INTEGER REFERENCES categories(id),
  subcategory_id   INTEGER REFERENCES subcategories(id),
  descricao        TEXT,
  data_lanc        TEXT NOT NULL, -- Data de lançamento
  data_venc        TEXT NOT NULL, -- Data de vencimento
  forma_pagto      TEXT,          -- Boleto, Pix, Transferência...
  parcelas_qtd     INTEGER NOT NULL DEFAULT 1,
  valor            REAL NOT NULL CHECK (valor >= 0),
  status           TEXT NOT NULL DEFAULT 'EM_ABERTO' CHECK (status IN ('EM_ABERTO','LIQUIDADO','CANCELADO')),
  banco_id_padrao  INTEGER REFERENCES bank_accounts(id), -- opcional: sugestão de banco
  created_by       INTEGER REFERENCES users(id),
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT
);

-- Baixas (Liquidações) - pode ter múltiplas por lançamento
CREATE TABLE IF NOT EXISTS payments (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  transaction_id  INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  company_id      INTEGER NOT NULL, -- redundância boa pra índices/consulta
  payment_date    TEXT NOT NULL,
  bank_id         INTEGER NOT NULL REFERENCES bank_accounts(id),
  amount          REAL NOT NULL CHECK (amount >= 0),
  interest        REAL NOT NULL DEFAULT 0,
  discount        REAL NOT NULL DEFAULT 0,
  doc_ref         TEXT,
  created_by      INTEGER REFERENCES users(id),
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fechamento de mês/ano por empresa
CREATE TABLE IF NOT EXISTS periods (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  month       INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  year        INTEGER NOT NULL CHECK (year BETWEEN 1900 AND 3000),
  status      TEXT NOT NULL CHECK (status IN ('OPEN','CLOSED')) DEFAULT 'OPEN',
  locked_at   TEXT,
  locked_by   INTEGER REFERENCES users(id),
  UNIQUE(company_id, month, year)
);

-- Log de auditoria (ações relevantes)
CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL DEFAULT (datetime('now')),
  user_id     INTEGER,
  action      TEXT NOT NULL,         -- e.g., 'INSERT transactions', 'UPDATE payments'
  table_name  TEXT NOT NULL,
  record_id   INTEGER,
  details     TEXT
);

-- --------------------- ÍNDICES ---------------------------------------------
CREATE INDEX IF NOT EXISTS idx_trans_company_venc ON transactions(company_id, data_venc);
CREATE INDEX IF NOT EXISTS idx_trans_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_payments_tx ON payments(transaction_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_entities_company ON entities(company_id);
CREATE INDEX IF NOT EXISTS idx_bank_company ON bank_accounts(company_id);

-- --------------------- VIEWS (consultas-chave) ------------------------------

-- View de listagem dos títulos com status calculado (considera atraso pela data atual)
CREATE VIEW IF NOT EXISTS vw_transactions_lista AS
SELECT
  t.id, t.company_id, t.tipo, t.entity_id, t.category_id, t.subcategory_id,
  t.descricao, t.data_lanc, t.data_venc, t.forma_pagto, t.parcelas_qtd,
  t.valor,
  CASE
    WHEN t.status = 'LIQUIDADO' THEN 'LIQUIDADO'
    WHEN date(t.data_venc) < date('now') THEN 'ATRASADO'
    ELSE 'EM_ABERTO'
  END AS status_calc,
  IFNULL((
    SELECT ROUND(SUM(p.amount + p.interest - p.discount), 2)
    FROM payments p
    WHERE p.transaction_id = t.id
  ), 0) AS total_pago
FROM transactions t;

-- View de fluxo de caixa (efeito caixa das baixas)
CREATE VIEW IF NOT EXISTS vw_fluxo_caixa AS
SELECT
  p.company_id,
  p.payment_date AS data,
  b.bank_name,
  b.account_name,
  CASE WHEN t.tipo='RECEBER'
       THEN (p.amount + p.interest - p.discount)
       ELSE -(p.amount + p.interest - p.discount)
  END AS valor_efeito,
  t.id AS transaction_id,
  p.id AS payment_id
FROM payments p
JOIN transactions t ON t.id = p.transaction_id
JOIN bank_accounts b ON b.id = p.bank_id;

-- DRE - competência (por data de lançamento)
CREATE VIEW IF NOT EXISTS vw_dre_competencia AS
SELECT
  company_id,
  strftime('%Y', data_lanc) AS ano,
  strftime('%m', data_lanc) AS mes,
  tipo,
  category_id,
  ROUND(SUM(valor), 2) AS total
FROM transactions
WHERE status <> 'CANCELADO'
GROUP BY company_id, ano, mes, tipo, category_id;

-- DRE - caixa (por data de pagamento)
CREATE VIEW IF NOT EXISTS vw_dre_caixa AS
SELECT
  p.company_id,
  strftime('%Y', p.payment_date) AS ano,
  strftime('%m', p.payment_date) AS mes,
  t.tipo,
  t.category_id,
  ROUND(SUM(CASE WHEN t.tipo='RECEBER'
                 THEN (p.amount + p.interest - p.discount)
                 ELSE -(p.amount + p.interest - p.discount) END), 2) AS total
FROM payments p
JOIN transactions t ON t.id = p.transaction_id
GROUP BY p.company_id, ano, mes, t.tipo, t.category_id;

-- --------------------- TRIGGERS --------------------------------------------

-- Bloqueio de movimentação quando o período estiver FECHADO
CREATE TRIGGER IF NOT EXISTS trg_trans_before_ins_period
BEFORE INSERT ON transactions
BEGIN
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = NEW.company_id
        AND p.month = CAST(strftime('%m', NEW.data_lanc) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', NEW.data_lanc) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado para lançamentos')
  END;
END;

CREATE TRIGGER IF NOT EXISTS trg_trans_before_upd_period
BEFORE UPDATE ON transactions
BEGIN
  -- Verifica velho e novo
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = OLD.company_id
        AND p.month = CAST(strftime('%m', OLD.data_lanc) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', OLD.data_lanc) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado (registro original)')
  END;
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = NEW.company_id
        AND p.month = CAST(strftime('%m', NEW.data_lanc) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', NEW.data_lanc) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado (registro novo)')
  END;
END;

CREATE TRIGGER IF NOT EXISTS trg_trans_before_del_period
BEFORE DELETE ON transactions
BEGIN
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = OLD.company_id
        AND p.month = CAST(strftime('%m', OLD.data_lanc) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', OLD.data_lanc) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado para exclusão')
  END;
END;

-- Bloqueio de pagamentos em mês fechado
CREATE TRIGGER IF NOT EXISTS trg_pay_before_ins_period
BEFORE INSERT ON payments
BEGIN
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = NEW.company_id
        AND p.month = CAST(strftime('%m', NEW.payment_date) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', NEW.payment_date) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado para baixas')
  END;
END;

CREATE TRIGGER IF NOT EXISTS trg_pay_before_upd_period
BEFORE UPDATE ON payments
BEGIN
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = OLD.company_id
        AND p.month = CAST(strftime('%m', OLD.payment_date) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', OLD.payment_date) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado (baixa original)')
  END;
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = NEW.company_id
        AND p.month = CAST(strftime('%m', NEW.payment_date) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', NEW.payment_date) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado (baixa nova)')
  END;
END;

CREATE TRIGGER IF NOT EXISTS trg_pay_before_del_period
BEFORE DELETE ON payments
BEGIN
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM periods p
      WHERE p.company_id = OLD.company_id
        AND p.month = CAST(strftime('%m', OLD.payment_date) AS INTEGER)
        AND p.year  = CAST(strftime('%Y', OLD.payment_date) AS INTEGER)
        AND p.status = 'CLOSED'
    )
    THEN RAISE(ABORT, 'Periodo fechado para exclusão de baixa')
  END;
END;

-- Atualiza saldo do banco e status do título nas operações de pagamentos
-- INSERT
CREATE TRIGGER IF NOT EXISTS trg_pay_after_ins_bank_status
AFTER INSERT ON payments
BEGIN
  -- Atualiza saldo do banco (entra se RECEBER, sai se PAGAR)
  UPDATE bank_accounts
  SET current_balance = current_balance + (
    SELECT CASE WHEN t.tipo='RECEBER'
                THEN (NEW.amount + NEW.interest - NEW.discount)
                ELSE -(NEW.amount + NEW.interest - NEW.discount) END
    FROM transactions t
    WHERE t.id = NEW.transaction_id
  )
  WHERE id = NEW.bank_id;

  -- Atualiza status do título
  UPDATE transactions
  SET status = CASE
      WHEN (
        SELECT ROUND(SUM(p.amount + p.interest - p.discount), 2)
        FROM payments p
        WHERE p.transaction_id = NEW.transaction_id
      ) >= ROUND(valor, 2) THEN 'LIQUIDADO'
      ELSE 'EM_ABERTO'
    END,
    updated_at = datetime('now')
  WHERE id = NEW.transaction_id;
END;

-- UPDATE (recalcula delta de banco e status)
CREATE TRIGGER IF NOT EXISTS trg_pay_after_upd_bank_status
AFTER UPDATE ON payments
BEGIN
  -- Remove efeito antigo do banco
  UPDATE bank_accounts
  SET current_balance = current_balance - (
    SELECT CASE WHEN t.tipo='RECEBER'
                THEN (OLD.amount + OLD.interest - OLD.discount)
                ELSE -(OLD.amount + OLD.interest - OLD.discount) END
    FROM transactions t
    WHERE t.id = OLD.transaction_id
  )
  WHERE id = OLD.bank_id;

  -- Aplica efeito novo no banco
  UPDATE bank_accounts
  SET current_balance = current_balance + (
    SELECT CASE WHEN t.tipo='RECEBER'
                THEN (NEW.amount + NEW.interest - NEW.discount)
                ELSE -(NEW.amount + NEW.interest - NEW.discount) END
    FROM transactions t
    WHERE t.id = NEW.transaction_id
  )
  WHERE id = NEW.bank_id;

  -- Atualiza status do (velho e novo) título se trocar referência
  UPDATE transactions
  SET status = CASE
      WHEN (
        SELECT ROUND(SUM(p.amount + p.interest - p.discount), 2)
        FROM payments p
        WHERE p.transaction_id = OLD.transaction_id
      ) >= ROUND(valor, 2) THEN 'LIQUIDADO'
      ELSE 'EM_ABERTO'
    END,
    updated_at = datetime('now')
  WHERE id = OLD.transaction_id;

  UPDATE transactions
  SET status = CASE
      WHEN (
        SELECT ROUND(SUM(p.amount + p.interest - p.discount), 2)
        FROM payments p
        WHERE p.transaction_id = NEW.transaction_id
      ) >= ROUND(valor, 2) THEN 'LIQUIDADO'
      ELSE 'EM_ABERTO'
    END,
    updated_at = datetime('now')
  WHERE id = NEW.transaction_id;
END;

-- DELETE
CREATE TRIGGER IF NOT EXISTS trg_pay_after_del_bank_status
AFTER DELETE ON payments
BEGIN
  -- Reverte efeito no banco
  UPDATE bank_accounts
  SET current_balance = current_balance - (
    SELECT CASE WHEN t.tipo='RECEBER'
                THEN (OLD.amount + OLD.interest - OLD.discount)
                ELSE -(OLD.amount + OLD.interest - OLD.discount) END
    FROM transactions t
    WHERE t.id = OLD.transaction_id
  )
  WHERE id = OLD.bank_id;

  -- Recalcula status do título
  UPDATE transactions
  SET status = CASE
      WHEN (
        SELECT ROUND(SUM(p.amount + p.interest - p.discount), 2)
        FROM payments p
        WHERE p.transaction_id = OLD.transaction_id
      ) >= ROUND(valor, 2) THEN 'LIQUIDADO'
      ELSE 'EM_ABERTO'
    END,
    updated_at = datetime('now')
  WHERE id = OLD.transaction_id;
END;
"""

# --------- SEED (permissões + admin + exemplos) ------------------------------
SEED_SQL = """
INSERT OR IGNORE INTO permission_types(code, name, description) VALUES
  ('CONTAS',             'Contas a Pagar/Receber', 'Acesso ao módulo de lançamentos e baixas'),
  ('BANCOS',             'Cadastro de Bancos',     'Criar/editar contas bancárias e saldos'),
  ('FORNECEDOR_CLIENTE', 'Fornecedor/Cliente',     'Cadastro de entidades'),
  ('NFE',                'Emissão NFS-e',          'Acesso a emissão/registro de NFS-e'),
  ('DRE',                'DRE',                    'Acesso ao demonstrativo de resultados');

-- Empresa de exemplo
INSERT OR IGNORE INTO companies (id, cnpj, razao_social, cidade, uf) VALUES
  (1, '00000000000000', 'EMPRESA DEMONSTRAÇÃO LTDA', 'Campo Grande', 'MS');

-- Conta bancária padrão
INSERT OR IGNORE INTO bank_accounts (company_id, bank_name, account_name, account_type, initial_balance, current_balance)
VALUES (1, 'CAIXA', 'Caixa', 'CAIXA', 0, 0);

-- Categorias iniciais (padrões comuns)
INSERT OR IGNORE INTO categories (company_id, name, tipo) VALUES
  (1, 'PRESTACAO DE SERVICOS', 'RECEBER'),
  (1, 'RETENCOES DE IMPOSTOS', 'PAGAR'),
  (1, 'DESPESAS OPERACIONAIS', 'PAGAR'),
  (1, 'DESPESAS DE ESCRITORIO', 'PAGAR'),
  (1, 'RECEITAS BANCARIAS', 'RECEBER');

-- Subcategorias de exemplo
INSERT OR IGNORE INTO subcategories (category_id, name)
SELECT c.id, 'OUTROS' FROM categories c WHERE c.company_id=1 AND c.name='DESPESAS OPERACIONAIS' AND c.tipo='PAGAR';

INSERT OR IGNORE INTO periods (company_id, month, year, status) VALUES
  (1, CAST(strftime('%m','now') AS INTEGER), CAST(strftime('%Y','now') AS INTEGER), 'OPEN');
"""

# --------- criação do banco --------------------------------------------------
def ensure_db(path: Path):
    new_db = not path.exists()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        if new_db:
            conn.executescript(SCHEMA_SQL)
            conn.executescript(SEED_SQL)
            conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            print("[OK] Esquema criado.")
        else:
            # poderíamos colocar migrações por versão aqui no futuro
            print("[OK] Banco já existia; validando esquema…")
            conn.executescript(SCHEMA_SQL)  # idempotente

def create_admin_user(path: Path, username="admin", password="admin123", name="Administrador"):
    with sqlite3.connect(path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cur.fetchone():
            print(f"[OK] Usuário admin '{username}' já existe.")
            return
        salt, pw_hash, iters = hash_password(password)
        cur.execute("""
            INSERT INTO users (name, username, password_salt, password_hash, iterations, is_admin)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (name, username, salt, pw_hash, iters))
        admin_id = cur.lastrowid
        # dá acesso à empresa 1 e libera todas as permissões
        cur.execute("INSERT OR IGNORE INTO user_company_access(user_id, company_id) VALUES(?, 1)", (admin_id,))
        cur.execute("SELECT id FROM permission_types")
        perm_ids = [row[0] for row in cur.fetchall()]
        cur.executemany("INSERT OR REPLACE INTO user_permissions(user_id, perm_id, allowed) VALUES(?, ?, 1)",
                        [(admin_id, pid) for pid in perm_ids])
        conn.commit()
        print(f"[OK] Usuário admin criado: username='{username}' senha='{password}' (altere no primeiro login).")

def list_objects(path: Path):
    with sqlite3.connect(path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name;")
        rows = cur.fetchall()
        print("\nObjetos criados (tabelas e views):")
        for name, typ in rows:
            print(f"  - {typ:5s}  {name}")
        # Mostra triggers
        cur.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name;")
        tr = cur.fetchall()
        print("\nTriggers:")
        for (name,) in tr:
            print(f"  - {name}")

if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    db_path = base / DB_FILE
    ensure_db(db_path)
    create_admin_user(db_path)  # username=admin / senha=admin123
    list_objects(db_path)
    print(f"\n[PRONTO] Banco disponível em: {db_path}")
