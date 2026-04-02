from flask import Flask, request, jsonify, send_file
import requests
import io
import os
from datetime import datetime

app = Flask(__name__)

# Credenciais Base
API_BASE = "https://intranet.netnew.com.br"
EMAIL_LOGIN = "chat@netnew.com.br"
SENHA_LOGIN = "SenhaChatbot123"

# Credenciais Zap Responder (Mantendo o ID do Atendimento para os disparos)
ZAP_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI2OTY5M2E0YTMzYjY1MDE1OTEwMDZkYzYiLCJhcGkiOnRydWUsImlhdCI6MTc3NTA2MjUyMH0.w-a4AlmPh6HbJzjXsCk9cgvLvgAvAG4QvY-g52JW6bA"
ZAP_DEPARTAMENTO_ID = "8cf962cd-82af-4984-a159-5ce3c12e8ccc" 

def obter_token():
    url = f"{API_BASE}/api/auth/login"
    payload = {'email': EMAIL_LOGIN, 'password': SENHA_LOGIN}
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json().get('data', {}).get('token')
    except:
        pass
    return None

# Rota 1: Agora ela recebe o código exato de cada fatura para baixar múltiplos boletos
@app.route('/webhook/gerar_boleto', methods=['GET', 'POST'])
def gerar_boleto():
    cod_cobranca = request.args.get('cod_cobranca')
    data_vencimento = request.args.get('vencimento')
    cpf = request.args.get('cpf', '00000000000')
    
    if not cod_cobranca or not data_vencimento:
        return jsonify({"erro": "Faltam parâmetros."}), 400

    token = obter_token()
    headers = {'Authorization': f'Bearer {token}'}
    
    payload_2avia = {'codCobranca': cod_cobranca, 'dataVencimento': data_vencimento, 'formato': 'PDF'}
    res_pdf = requests.post(f"{API_BASE}/api/v1/cliente/faturas/2avia/", headers=headers, data=payload_2avia, timeout=20)
    
    if res_pdf.status_code == 200 and res_pdf.content.startswith(b'%PDF'):
        return send_file(
            io.BytesIO(res_pdf.content), mimetype='application/pdf', 
            as_attachment=True, download_name=f'Boleto_{cpf}_{cod_cobranca}.pdf'
        )
    return jsonify({"erro": "Erro ao gerar PDF."}), 500

# Rota 2: O MOTOR DE REGRAS DE NEGÓCIO
@app.route('/webhook/enviar_pdf_chat', methods=['GET', 'POST'])
def enviar_pdf_chat():
    cpf = request.args.get('cpf')
    telefone = request.args.get('telefone')
    
    if not cpf or not telefone:
        return jsonify({"status": "erro"}), 400
        
    telefone_limpo = "55" + "".join(filter(str.isdigit, telefone)) if not "".join(filter(str.isdigit, telefone)).startswith("55") else "".join(filter(str.isdigit, telefone))
    cpf_limpo = "".join(filter(str.isdigit, cpf))
    
    token = obter_token()
    headers_netnew = {'Authorization': f'Bearer {token}'}

    # Busca faturas abertas
    res_faturas = requests.get(f"{API_BASE}/api/v1/cliente/faturas/abertas/{cpf_limpo}", headers=headers_netnew, timeout=15)
    dados_faturas = res_faturas.json().get('data', []) if res_faturas.status_code == 200 else []
        
    if not dados_faturas:
        res_hist = requests.get(f"{API_BASE}/api/v1/cliente/faturas/historico/{cpf_limpo}", headers=headers_netnew, timeout=15)
        if res_hist.status_code == 200:
            lista = res_hist.json().get('data', []) if isinstance(res_hist.json(), dict) else res_hist.json()
            dados_faturas = [f for f in lista if f.get('status') != 'PAGO']

    # REGRA 3: FALSO POSITIVO (Não deve nada)
    if not dados_faturas:
        return jsonify({"status": "sem_pendencias"})

    headers_zap = {"Authorization": f"Bearer {ZAP_TOKEN}", "Content-Type": "application/json"}
    hoje = datetime.now()
    max_atraso_dias = 0
    texto_meses = "📄 *Resumo das suas faturas:*\n\n"
    
    lista_faturas = dados_faturas if isinstance(dados_faturas, list) else [dados_faturas]

    for fatura in lista_faturas:
        cod_cobranca = fatura.get('codcobranca') or fatura.get('codCobranca') or fatura.get('id')
        data_vencimento = fatura.get('datavencimento') or fatura.get('dataVencimento')
        if not cod_cobranca or not data_vencimento: continue
            
        # REGRA 2: IDENTIFICAÇÃO DOS MESES E ATRASO
        try:
            data_obj = datetime.strptime(data_vencimento[:10], "%Y-%m-%d")
            mes_formatado = data_obj.strftime("%m/%Y")
            dias_atraso = (hoje - data_obj).days
            
            if dias_atraso > max_atraso_dias: max_atraso_dias = dias_atraso
                
            if dias_atraso > 0:
                texto_meses += f"👉 Fatura do mês {mes_formatado} (Vencida há {dias_atraso} dias)\n"
            else:
                texto_meses += f"👉 Fatura do mês {mes_formatado} (A vencer)\n"
        except: pass
            
        # Envia os PDFs fisicamente
        payload_pdf = {"type": "document", "number": telefone_limpo, "url": f"https://api-netnew.onrender.com/webhook/gerar_boleto?cod_cobranca={cod_cobranca}&vencimento={data_vencimento}&cpf={cpf_limpo}"}
        requests.post(f"https://api.zapresponder.com.br/api/whatsapp/message/{ZAP_DEPARTAMENTO_ID}", json=payload_pdf, headers=headers_zap)

    # Envia o texto de resumo
    requests.post(f"https://api.zapresponder.com.br/api/whatsapp/message/{ZAP_DEPARTAMENTO_ID}", json={"type": "text", "message": texto_meses, "number": telefone_limpo}, headers=headers_zap)

    # REGRA 1: BLOQUEIO (>2 dias)
    if max_atraso_dias > 2:
        return jsonify({"status": "bloqueado"})
    return jsonify({"status": "liberado"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
