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
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json().get('data', {}).get('token')
    except Exception as e:
        print(f"Erro ao autenticar: {e}")
    return None

@app.route('/webhook/gerar_boleto', methods=['GET', 'POST'])
def gerar_boleto():
    cpf = request.args.get('cpf')
    
    if not cpf:
        return jsonify({"erro": "CPF/CNPJ não fornecido na requisição."}), 400

    # Limpa pontos e traços caso o Zap Responder envie formatado
    cpf = "".join(filter(str.isdigit, cpf))

    token = obter_token()
    if not token:
        return jsonify({"erro": "Falha de autenticação na API NetNew."}), 500

    headers = {'Authorization': f'Bearer {token}'}

    # --- PASSO 1: Buscar Faturas Abertas (A Vencer) ---
    url_faturas = f"{API_BASE}/api/v1/cliente/faturas/abertas/{cpf}"
    res_faturas = requests.get(url_faturas, headers=headers, timeout=15)
    
    dados_faturas = []
    if res_faturas.status_code == 200:
        dados_faturas = res_faturas.json()
    
    # --- PASSO 2: Se não achou nas abertas, busca no Histórico (Vencidas) ---
    if not dados_faturas or (isinstance(dados_faturas, list) and len(dados_faturas) == 0):
        url_historico = f"{API_BASE}/api/v1/cliente/faturas/historico/{cpf}"
        res_hist = requests.get(url_historico, headers=headers, timeout=15)
        
        if res_hist.status_code == 200:
            todos_dados = res_hist.json()
            # Filtra apenas o que não está PAGO no histórico
            lista = todos_dados if isinstance(todos_dados, list) else todos_dados.get('data', [])
            dados_faturas = [f for f in lista if f.get('status') != 'PAGO']

    if not dados_faturas:
        return jsonify({"mensagem": f"Nenhuma fatura pendente encontrada para o CPF {cpf}."}), 404

    # Pega a primeira fatura pendente da lista
    fatura_atual = dados_faturas[0] if isinstance(dados_faturas, list) else dados_faturas
    
    # Tenta localizar o código de cobrança em diferentes chaves possíveis
    cod_cobranca = fatura_atual.get('codCobranca') or fatura_atual.get('id') or fatura_atual.get('codigo')
    data_vencimento = fatura_atual.get('dataVencimento')

    if not cod_cobranca:
        return jsonify({"erro": "Código de cobrança não localizado nos dados da fatura.", "debug": fatura_atual}), 404

    # --- PASSO 3: Gerar o PDF da 2ª Via ---
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

if __name__ == '__main__':
    # No Render a porta é definida pela variável de ambiente PORT
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
