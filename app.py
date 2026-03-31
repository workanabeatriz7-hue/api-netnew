from flask import Flask, request, jsonify, send_file
import requests
import io

app = Flask(__name__)

# Credenciais Base da NetNew
API_BASE = "https://intranet.netnew.com.br"
EMAIL_LOGIN = "chat@netnew.com.br"
SENHA_LOGIN = "SenhaChatbot123"

def obter_token():
    url = f"{API_BASE}/api/auth/login"
    payload = {'email': EMAIL_LOGIN, 'password': SENHA_LOGIN}
    resp = requests.post(url, data=payload)
    if resp.status_code == 200:
        return resp.json().get('data', {}).get('token')
    return None

@app.route('/webhook/gerar_boleto', methods=['GET', 'POST'])
def gerar_boleto():
    cpf = request.args.get('cpf')
    
    if not cpf:
        return jsonify({"erro": "CPF/CNPJ não fornecido na requisição."}), 400

    token = obter_token()
    if not token:
        return jsonify({"erro": "Falha de autenticação na API NetNew."}), 500

    headers = {'Authorization': f'Bearer {token}'}

    # Consultar Faturas Abertas
    url_faturas = f"{API_BASE}/api/v1/cliente/faturas/abertas/{cpf}"
    res_faturas = requests.get(url_faturas, headers=headers)
    
    if res_faturas.status_code != 200:
        return jsonify({"erro": "Não foi possível consultar as faturas."}), 500
        
    dados_faturas = res_faturas.json()
    
    if not dados_faturas or len(dados_faturas) == 0:
        return jsonify({"mensagem": "Nenhuma fatura em aberto encontrada para este CPF."}), 404

    # Pega o primeiro boleto da lista
    fatura_atual = dados_faturas[0] if isinstance(dados_faturas, list) else dados_faturas.get('data', [{}])[0]
    
    cod_cobranca = fatura_atual.get('codCobranca')
    data_vencimento = fatura_atual.get('dataVencimento')

    if not cod_cobranca:
        return jsonify({"erro": "Código de cobrança não localizado."}), 404

    # Gerar o PDF
    url_2avia = f"{API_BASE}/api/v1/cliente/faturas/2avia/"
    payload_2avia = {
        'codCobranca': cod_cobranca,
        'dataVencimento': data_vencimento,
        'formato': 'PDF'
    }
    
    res_pdf = requests.post(url_2avia, headers=headers, data=payload_2avia)
    
    if res_pdf.status_code == 200 and res_pdf.content.startswith(b'%PDF'):
        return send_file(
            io.BytesIO(res_pdf.content),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'Boleto_{cpf}.pdf'
        )
    else:
        return jsonify({"erro": "Falha ao gerar o arquivo PDF."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)