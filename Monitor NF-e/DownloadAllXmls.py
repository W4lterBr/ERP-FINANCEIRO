# DownloadAllXmls.py
# =============================================================================
# Lê XMLs de NF-e (procNFe/NFe), extrai campos e grava em notas.db (tabela
# notas_detalhadas). Robusto a esquemas diferentes:
# - NÃO usa 'cnpj_cpf' (usa 'cnpj_emitente' e 'cnpj_destinatario').
# - Garante colunas necessárias com ALTER TABLE se faltarem.
# - UPSERT por 'chave' (update se existir, insert se não).
# =============================================================================

import os
import sys
import logging
import sqlite3
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional, List

# ---------- Config logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("DownloadAllXmls")

# ---------- Caminhos ----------
SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "notas.db"
XML_ROOT = SCRIPT_DIR / "xmls"  # estrutura: xmls/<cnpj>/<yyyy-mm>/*.xml

# ---------- Namespaces NFe ----------
NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

# ---------- Helpers ----------
def only_digits(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def br_date(d: str) -> str:
    """Converte 'YYYY-MM-DD' ou 'YYYY-MM-DDThh:mm:ss' para 'dd/mm/YYYY'."""
    if not d:
        return ""
    try:
        if "T" in d:
            d = d.split("T", 1)[0]
        return datetime.fromisoformat(d).strftime("%d/%m/%Y")
    except Exception:
        # já pode estar em dd/mm/yyyy
        return d

def xml_text(elem: Optional[ET.Element]) -> str:
    return (elem.text or "").strip() if elem is not None else ""

def find1(root: Optional[ET.Element], path: str) -> str:
    if root is None:
        return ""
    el = root.find(path, NS)
    return xml_text(el)

def get_first(root: Optional[ET.Element], paths: List[str]) -> str:
    for p in paths:
        t = find1(root, p)
        if t:
            return t
    return ""

# ---------- Banco ----------
REQUIRED_COLS = [
    ("chave", "TEXT"),
    ("numero", "TEXT"),
    ("data_emissao", "TEXT"),
    ("cnpj_emitente", "TEXT"),
    ("nome_emitente", "TEXT"),
    ("cnpj_destinatario", "TEXT"),
    ("nome_destinatario", "TEXT"),
    ("valor", "TEXT"),
    ("cfop", "TEXT"),
    ("tipo", "TEXT"),
    ("vencimento", "TEXT"),
    ("status", "TEXT"),
    ("natureza", "TEXT"),
    ("ie_tomador", "TEXT"),
    ("uf", "TEXT"),
]

def ensure_table(conn: sqlite3.Connection):
    """Garante que 'notas_detalhadas' exista e tenha as colunas necessárias."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notas_detalhadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    """)
    conn.commit()

    cur.execute("PRAGMA table_info(notas_detalhadas)")
    existing_cols = {row[1] for row in cur.fetchall()}

    for col, ctype in REQUIRED_COLS:
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE notas_detalhadas ADD COLUMN {col} {ctype}")
            log.debug("ADD COLUMN %s %s", col, ctype)
    conn.commit()

def get_existing_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]

def record_exists(conn: sqlite3.Connection, chave: str) -> bool:
    cur = conn.execute("SELECT 1 FROM notas_detalhadas WHERE chave=?", (chave,))
    return cur.fetchone() is not None

def upsert_nota(conn: sqlite3.Connection, rec: Dict[str, Any]):
    cols_in_db = set(get_existing_columns(conn, "notas_detalhadas"))
    data = {k: v for k, v in rec.items() if k in cols_in_db}

    if "chave" not in data or not data["chave"]:
        raise ValueError("Registro sem 'chave'.")

    if record_exists(conn, data["chave"]):
        assigns = ", ".join(f"{k}=?" for k in data.keys() if k != "chave")
        values = [v for k, v in data.items() if k != "chave"]
        values.append(data["chave"])
        sql = f"UPDATE notas_detalhadas SET {assigns} WHERE chave=?"
        conn.execute(sql, values)
    else:
        keys = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO notas_detalhadas ({keys}) VALUES ({placeholders})"
        conn.execute(sql, list(data.values()))

# ---------- Parser de XML ----------
def find_nfe_node(root: ET.Element) -> Optional[ET.Element]:
    """Retorna o nó <NFe> (pode estar dentro de <procNFe>) sem usar avaliação booleana do Element."""
    nfe_node = root.find(".//nfe:NFe", NS)
    if nfe_node is not None:
        return nfe_node
    # caso o próprio root seja NFe
    if isinstance(root.tag, str) and root.tag.endswith("NFe"):
        return root
    return None

def parse_nfe_xml(xml_path: Path) -> Optional[Dict[str, Any]]:
    """
    Suporta 'procNFe' e 'NFe'.
    Retorna dict com campos para gravar no banco.
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        nfe_node = find_nfe_node(root)
        if nfe_node is None:
            log.warning("NFe não encontrada em: %s", xml_path)
            return None

        inf = nfe_node.find(".//nfe:infNFe", NS)
        if inf is None:
            log.warning("infNFe ausente em: %s", xml_path)
            return None

        chave = (inf.get("Id") or "").replace("NFe", "").strip()[-44:]

        ide  = nfe_node.find(".//nfe:ide", NS)
        emit = nfe_node.find(".//nfe:emit", NS)
        dest = nfe_node.find(".//nfe:dest", NS)
        total = nfe_node.find(".//nfe:total/nfe:ICMSTot", NS)
        prot  = root.find(".//nfe:protNFe/nfe:infProt", NS)  # pode não existir

        numero = find1(ide, "nfe:nNF")
        dEmi   = get_first(ide, ["nfe:dhEmi", "nfe:dEmi"])
        natOp  = find1(ide, "nfe:natOp")
        cUF    = find1(ide, "nfe:cUF")

        # CFOP do primeiro item
        cfop = find1(nfe_node, ".//nfe:det/nfe:prod/nfe:CFOP")

        valor = find1(total, "nfe:vNF")

        # Emitente
        xNome_emit = find1(emit, "nfe:xNome")
        cnpj_emit  = get_first(emit, ["nfe:CNPJ", "nfe:CPF"])

        # Destinatário
        xNome_dest = find1(dest, "nfe:xNome")
        cnpj_dest  = get_first(dest, ["nfe:CNPJ", "nfe:CPF"])

        # Status do protocolo (se houver)
        status = ""
        if prot is not None:
            cStat = find1(prot, "nfe:cStat")
            xMot  = find1(prot, "nfe:xMotivo")
            if cStat:
                status = f"{xMot} ({cStat})" if xMot else cStat

        # Tipo / modelo
        modelo = find1(ide, "nfe:mod")
        tipo = "NFe" if modelo == "55" else ("NFCe" if modelo == "65" else (modelo or ""))

        # Vencimento (1ª duplicata, se houver)
        venc = get_first(nfe_node, ["nfe:cobr/nfe:dup/nfe:dVenc"])

        rec = {
            "chave": chave,
            "numero": numero,
            "data_emissao": br_date(dEmi),
            "cnpj_emitente": only_digits(cnpj_emit),
            "nome_emitente": xNome_emit,
            "cnpj_destinatario": only_digits(cnpj_dest),
            "nome_destinatario": xNome_dest,
            "valor": valor.replace(".", ",") if valor else "",
            "cfop": cfop,
            "tipo": tipo,
            "vencimento": br_date(venc),
            "status": status or ("Autorizado o uso da NF-e" if (prot is not None) else ""),
            "natureza": natOp,
            "ie_tomador": "",
            "uf": cUF,  # numérico (ex.: 50 para MS)
        }
        return rec
    except Exception as e:
        log.error("Falha ao parsear XML %s: %s", xml_path, e)
        return None

# ---------- Varredura ----------
def iter_xmls(root_dir: Path):
    """
    Espera estrutura: xmls/<cnpj>/<YYYY-MM>/*.xml
    """
    if not root_dir.exists():
        return
    for cnpj_dir in sorted(root_dir.iterdir()):
        if not cnpj_dir.is_dir():
            continue
        for ym_dir in sorted(cnpj_dir.iterdir()):
            if not ym_dir.is_dir():
                continue
            for xmlf in sorted(ym_dir.glob("*.xml")):
                yield xmlf

# ---------- Main ----------
def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_table(conn)

        saved = 0
        for xmlf in iter_xmls(XML_ROOT):
            try:
                rec = parse_nfe_xml(xmlf)
                if not rec:
                    continue
                upsert_nota(conn, rec)
                saved += 1
            except Exception as e:
                log.error("[ERRO ao processar %s]: %s", xmlf, e)
        conn.commit()
        log.info("=== %d notas detalhadas salvas/atualizadas ===", saved)
        print(f"[RESUMO] {saved} notas detalhadas salvas/atualizadas no banco.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
