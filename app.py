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
    except:
        pass
    return None

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
    try:
        res_pdf = requests.post(f"{API_BASE}/api/v1/cliente/faturas/2avia/", headers=headers, data=payload_2avia, timeout=20)
        if res_pdf.status_code == 200 and res_pdf.content.startswith(b'%PDF'):
            return send_file(
                io.BytesIO(res_pdf.content), mimetype='application/pdf', 
                as_attachment=True, download_name=f'Boleto_{cpf}_{cod_cobranca}.pdf'
            )
    except:
        pass
        
    return jsonify({"erro": "Erro ao gerar PDF."}), 500

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

    dados_faturas = []
    
    # BUSCA 1: Faturas Abertas
    try:
        res_abertas = requests.get(f"{API_BASE}/api/v1/cliente/completo/faturas/abertas/{cpf_limpo}", headers=headers_netnew, timeout=15)
        if res_abertas.status_code == 200:
            lista_abertas = res_abertas.json().get('data', [])
            if isinstance(lista_abertas, list):
                dados_faturas.extend(lista_abertas)
    except:
        pass
        
    # BUSCA 2: Faturas Vencidas
    try:
        res_vencidas = requests.get(f"{API_BASE}/api/v1/cliente/completo/faturas/vencidas/{cpf_limpo}", headers=headers_netnew, timeout=15)
        if res_vencidas.status_code == 200:
            lista_vencidas = res_vencidas.json().get('data', [])
            if isinstance(lista_vencidas, list):
                dados_faturas.extend(lista_vencidas)
    except:
        pass

    # Filtragem para remover duplicatas e títulos pagos (por segurança)
    faturas_filtradas = []
    ids_vistos = set()
    for f in dados_faturas:
        if not isinstance(f, dict): continue
        cod = f.get('codcobranca') or f.get('codCobranca') or f.get('id')
        
        # Converte o status para maiúsculo para garantir que não passe nada quitado
        status_fatura = str(f.get('status', '')).upper()
        
        if cod and cod not in ids_vistos and status_fatura != 'PAGO':
            faturas_filtradas.append(f)
            ids_vistos.add(cod)

    if not faturas_filtradas:
        return jsonify({"status": "sem_pendencias"})

    headers_zap = {"Authorization": f"Bearer {ZAP_TOKEN}", "Content-Type": "application/json"}
    hoje = datetime.now()
    max_atraso_dias = 0
    texto_meses = "📄 *Resumo das suas faturas:*\n\n"
    
    for fatura in faturas_filtradas:
        cod_cobranca = fatura.get('codcobranca') or fatura.get('codCobranca') or fatura.get('id')
        data_vencimento = fatura.get('datavencimento') or fatura.get('dataVencimento')
        if not cod_cobranca or not data_vencimento: continue
            
        try:
            # Tenta ler no padrão do banco (YYYY-MM-DD), se falhar, lê no padrão BR (DD/MM/YYYY)
            try:
                data_obj = datetime.strptime(data_vencimento[:10], "%Y-%m-%d")
            except ValueError:
                data_obj = datetime.strptime(data_vencimento[:10], "%d/%m/%Y")
            
            mes_formatado = data_obj.strftime("%m/%Y")
            dias_atraso = (hoje - data_obj).days
            
            if dias_atraso > max_atraso_dias: 
                max_atraso_dias = dias_atraso
                
            if dias_atraso > 0:
                texto_meses += f"👉 Fatura de {mes_formatado} (Vencida há {dias_atraso} dias)\n"
            else:
                texto_meses += f"👉 Fatura de {mes_formatado} (A vencer)\n"
        except: 
            pass
            
        payload_pdf = {"type": "document", "number": telefone_limpo, "url": f"https://api-netnew.onrender.com/webhook/gerar_boleto?cod_cobranca={cod_cobranca}&vencimento={data_vencimento}&cpf={cpf_limpo}"}
        requests.post(f"https://api.zapresponder.com.br/api/whatsapp/message/{ZAP_DEPARTAMENTO_ID}", json=payload_pdf, headers=headers_zap)

    requests.post(f"https://api.zapresponder.com.br/api/whatsapp/message/{ZAP_DEPARTAMENTO_ID}", json={"type": "text", "message": texto_meses, "number": telefone_limpo}, headers=headers_zap)

    if max_atraso_dias > 2:
        return jsonify({"status": "bloqueado"})
    return jsonify({"status": "liberado"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
