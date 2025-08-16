import os
import base64
import gzip
from lxml import etree

# Diretórios
DIR_XML_RESPOSTA = r"C:\Users\Walter\Documents\Arquivo Walter\BOT - Busca NFE\xml_resposta_sefaz"
DIR_SAIDA_XML = r"C:\Users\Walter\Documents\Arquivo Walter\BOT - Busca NFE\xml_extraidos"

os.makedirs(DIR_SAIDA_XML, exist_ok=True)

def extrair_e_salvar_doczip(arquivo_xml):
    print(f"Processando: {arquivo_xml}")

    with open(arquivo_xml, 'rb') as f:
        conteudo = f.read()
        # Garante que começa do início correto do XML
        start = conteudo.find(b'<?xml')
        if start != -1:
            conteudo = conteudo[start:]

    # Parseia com lxml (mais tolerante)
    root = etree.fromstring(conteudo)

    # Busca todos os docZip em qualquer namespace
    for doczip in root.xpath('.//ns:docZip', namespaces={'ns': 'http://www.portalfiscal.inf.br/nfe'}):
        nsu = doczip.attrib.get('NSU', 'sem_nsu')
        schema = doczip.attrib.get('schema', 'sem_schema')
        conteudo_zip = doczip.text

        try:
            dados_xml = gzip.decompress(base64.b64decode(conteudo_zip))
            if 'procNFe' in schema or 'resNFe' in schema:
                filename = f"{nsu}_{schema}.xml"
            elif 'procEvento' in schema or 'resEvento' in schema:
                filename = f"{nsu}_{schema}.xml"
            else:
                filename = f"{nsu}_{schema}.xml"

            caminho_saida = os.path.join(DIR_SAIDA_XML, filename)
            with open(caminho_saida, "wb") as f:
                f.write(dados_xml)
            print(f"  >> Salvo: {caminho_saida}")
        except Exception as e:
            print(f"  !! Erro ao descompactar NSU {nsu}: {e}")

def processar_todos_xmls(diretorio):
    for fname in os.listdir(diretorio):
        if fname.lower().endswith('.xml'):
            extrair_e_salvar_doczip(os.path.join(diretorio, fname))

if __name__ == "__main__":
    processar_todos_xmls(DIR_XML_RESPOSTA)
    print("Processamento concluído!")
