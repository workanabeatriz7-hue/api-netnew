from flask import Flask, request, jsonify, send_file
import requests
import io
import os

app = Flask(__name__)

# Credenciais Base da NetNew
API_BASE = "https://intranet.netnew.com.br"
EMAIL_LOGIN = "chat@netnew.com.br"
SENHA_LOGIN = "SenhaChatbot123"

# Credenciais Zap Responder
ZAP_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI2OTY5M2E0YTMzYjY1MDE1OTEwMDZkYzYiLCJhcGkiOnRydWUsImlhdCI6MTc3NTA2MjUyMH0.w-a4AlmPh6HbJzjXsCk9cgvLvgAvAG4QvY-g52JW6bA"
ZAP_DEPARTAMENTO_ID = "8cf962cd-82af-4984-a159-5ce3c12e8ccc"

def obter_token():
    url = f"{API_BASE}/api/auth/login"
    payload = {'email': EMAIL_LOGIN, 'password': SENHA_LOGIN}
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json().get('data', {}).get('token')
    except Exception as e:
        print(f"Erro ao autenticar: {e}")
    return None

# Rota 1: Apenas gera o PDF (a que você já testou e funciona)
@app.route('/webhook/gerar_boleto', methods=['GET', 'POST'])
def gerar_boleto():
    cpf = request.args.get('cpf')
    
    if not cpf:
        return jsonify({"erro": "CPF/CNPJ não fornecido na requisição."}), 400

    cpf = "".join(filter(str.isdigit, cpf))

    token = obter_token()
    if not token:
        return jsonify({"erro": "Falha de autenticação na API NetNew."}), 500

    headers = {'Authorization': f'Bearer {token}'}

    url_faturas = f"{API_BASE}/api/v1/cliente/faturas/abertas/{cpf}"
    res_faturas = requests.get(url_faturas, headers=headers, timeout=15)
    
    dados_faturas = []
    if res_faturas.status_code == 200:
        dados_faturas = res_faturas.json()
    
    if not dados_faturas or (isinstance(dados_faturas, list) and len(dados_faturas) == 0):
        url_historico = f"{API_BASE}/api/v1/cliente/faturas/historico/{cpf}"
        res_hist = requests.get(url_historico, headers=headers, timeout=15)
        
        if res_hist.status_code == 200:
            todos_dados = res_hist.json()
            lista = todos_dados if isinstance(todos_dados, list) else todos_dados.get('data', [])
            dados_faturas = [f for f in lista if f.get('status') != 'PAGO']

    if not dados_faturas:
        return jsonify({"mensagem": f"Nenhuma fatura pendente encontrada para o CPF {cpf}."}), 404

    fatura_atual = dados_faturas[0] if isinstance(dados_faturas, list) else dados_faturas
    
    cod_cobranca = fatura_atual.get('codcobranca') or fatura_atual.get('codCobranca') or fatura_atual.get('id')
    data_vencimento = fatura_atual.get('datavencimento') or fatura_atual.get('dataVencimento')

    if not cod_cobranca:
        return jsonify({"erro": "Código de cobrança não localizado nos dados da fatura.", "debug": fatura_atual}), 404

    url_2avia = f"{API_BASE}/api/v1/cliente/faturas/2avia/"
    
    payload_2avia = {
        'codCobranca': cod_cobranca,
        'dataVencimento': data_vencimento,
        'formato': 'PDF'
    }
    
    res_pdf = requests.post(url_2avia, headers=headers, data=payload_2avia, timeout=20)
    
    if res_pdf.status_code == 200 and res_pdf.content.startswith(b'%PDF'):
        return send_file(
            io.BytesIO(res_pdf.content),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'Boleto_{cpf}.pdf'
        )
    else:
        return jsonify({"erro": "A API NetNew não retornou um arquivo PDF válido.", "status_code": res_pdf.status_code}), 500


# Rota 2: A MÁGICA FINAL - Empurra o PDF ativamente para o WhatsApp
@app.route('/webhook/enviar_pdf_chat', methods=['GET', 'POST'])
def enviar_pdf_chat():
    cpf = request.args.get('cpf')
    telefone = request.args.get('telefone')
    
    if not cpf or not telefone:
        return jsonify({"erro": "Faltam parâmetros"}), 400
        
    # Limpa o telefone e garante que começa com 55 (padrão do Brasil)
    telefone_limpo = "".join(filter(str.isdigit, telefone))
    if not telefone_limpo.startswith("55"):
        telefone_limpo = "55" + telefone_limpo
        
    # Esse é o link do Render que gera o PDF (o Zap Responder vai acessar ele por baixo dos panos)
    url_do_pdf = f"https://api-netnew.onrender.com/webhook/gerar_boleto?cpf={cpf}"
    
    url_disparo_zap = f"https://api.zapresponder.com.br/api/whatsapp/message/{ZAP_DEPARTAMENTO_ID}"
    headers_zap = {
        "Authorization": f"Bearer {ZAP_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload_zap = {
        "type": "document",
        "number": telefone_limpo,
        "url": url_do_pdf
    }
    
    # Executa o disparo do arquivo
    res = requests.post(url_disparo_zap, json=payload_zap, headers=headers_zap)
    
    return jsonify({"status": "comando_enviado", "retorno_zap": res.text})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
