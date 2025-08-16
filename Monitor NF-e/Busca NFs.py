from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os

# Caminho para pasta de download
PASTA_DOWNLOAD = os.path.abspath(os.path.dirname(__file__))

chrome_options = Options()
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": PASTA_DOWNLOAD,
    "download.prompt_for_download": False,
    "directory_upgrade": True
})

driver = webdriver.Chrome(options=chrome_options)

print("Acesse https://www.nfse.gov.br/EmissorNacional/Login?ReturnUrl=%2fEmissorNacional%2fDashboard")
print("Faça login via certificado digital MANUALMENTE.")
driver.get("https://www.nfse.gov.br/EmissorNacional/Login?ReturnUrl=%2fEmissorNacional%2fDashboard")

input("Quando você estiver logado e na tela de 'Notas Recebidas', pressione ENTER para o robô começar...")

wait = WebDriverWait(driver, 30)

while True:
    # Aguarda todos os ícones de opções (três pontinhos) aparecerem
    opcoes = driver.find_elements(By.CSS_SELECTOR, ".glyphicon.glyphicon-option-vertical")
    if not opcoes:
        print("Nenhum registro encontrado, ou acabou a lista!")
        break

    for idx, botao in enumerate(opcoes):
        try:
            driver.execute_script("arguments[0].scrollIntoView();", botao)
            ActionChains(driver).move_to_element(botao).click().perform()
            time.sleep(1)

            # Espera abrir o popover-content
            popover = wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".popover-content"))
            )

            # Baixa o XML
            try:
                link_xml = popover.find_element(By.XPATH, ".//a[contains(.,'Download XML')]")
                link_xml.click()
                print(f"[{idx+1}] XML baixado.")
                time.sleep(1.2)
            except Exception as e:
                print("Não encontrou o botão de download XML:", e)

            # Baixa o PDF
            try:
                link_pdf = popover.find_element(By.XPATH, ".//a[contains(.,'Download DANFS-e')]")
                link_pdf.click()
                print(f"[{idx+1}] PDF baixado.")
                time.sleep(1.2)
            except Exception as e:
                print("Não encontrou o botão de download PDF:", e)

            # Fecha o popover clicando fora ou no botão de fechar
            driver.find_element(By.TAG_NAME, "body").click()
            time.sleep(0.7)

        except Exception as err:
            print("Erro ao baixar XML/PDF:", err)
            continue

    # Checa se há botão de próxima página (caso tenha paginação)
    try:
        proximo = driver.find_element(By.XPATH, "//a[contains(.,'Próxima')]")
        if proximo.is_enabled():
            proximo.click()
            print("Avançando para próxima página...")
            time.sleep(3)
        else:
            print("Não há próxima página. Fim dos downloads.")
            break
    except Exception:
        print("Não encontrou botão de próxima página. Processo finalizado.")
        break

print("Download de todos os XMLs e PDFs finalizado.")
driver.quit()
