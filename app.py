from flask import Flask, jsonify, request, send_file
from pymongo import MongoClient, ASCENDING
import os, json, asyncio, csv, io
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
# System program ID (native): all 1s
SYS_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
from anchorpy import Program, Provider, Wallet, Idl
from pathlib import Path
from reportlab.pdfgen import canvas as pdf_canvas

app = Flask(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────
MONGO_URI       = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME         = os.getenv("DB_NAME", "chain_of_custody")
SOLANA_RPC_URL  = os.getenv("SOLANA_RPC_URL", "http://127.0.0.1:8899")
PROGRAM_ID      = Pubkey.from_string(
    os.getenv("PROGRAM_ID", "8ZKteuY8Ro67u6G9ySTmNA1URo9KFjAS6iPoNQKBjrDN")
)
AUTHORITY_KEY   = os.getenv("AUTHORITY_KEYPAIR", "~/.config/solana/id.json")
ANCHOR_IDL_PATH = os.getenv(
    "ANCHOR_IDL_PATH",
    "/Users/lalkattil/Desktop/DavisHacks2025/chain_custody/target/idl/chain_custody.json",
)

# ─── Initialize MongoDB ─────────────────────────────────────────────────────
mongo_client   = MongoClient(MONGO_URI)
db             = mongo_client[DB_NAME]
materials_col  = db.materials
transfers_col  = db.transfers
signers_col    = db.signers

# Create indexes
materials_col.create_index([("materialId", ASCENDING)], unique=True)
transfers_col.create_index([("materialId", ASCENDING), ("sequence", ASCENDING)], unique=True)
signers_col.create_index([("pubkey", ASCENDING)], unique=True)

# ─── Solana & Anchor Helpers ────────────────────────────────────────────────

def load_local_keypair(path: str) -> Keypair:
    real_path = os.path.expanduser(path)
    if not os.path.exists(real_path):
        raise FileNotFoundError(f"Solana keypair not found at {real_path}")
    with open(real_path, 'r') as f:
        data = json.load(f)
    return Keypair.from_bytes(bytes(data))

async def _init_provider():
    client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
    auth   = load_local_keypair(AUTHORITY_KEY)
    wallet = Wallet(auth)
    return Provider(client, wallet)

async def _load_program(provider: Provider) -> Program:
    # Read IDL JSON text
    raw = Path(ANCHOR_IDL_PATH).read_text()
    # Normalize legacy Anchor output: 'writable' -> 'isMut', 'signer' -> 'isSigner'
    raw = raw.replace('"writable"', '"isMut"').replace('"signer"', '"isSigner"')
    # Inject missing account struct definitions: merge in 'type' from top-level types
    data = json.loads(raw)
    type_map = {t['name']: t['type'] for t in data.get('types', [])}
    for acct in data.get('accounts', []):
        if 'type' not in acct and acct['name'] in type_map:
            acct['type'] = type_map[acct['name']]
        # Instantiate the IDL and program client
    raw_json = json.dumps(data)
    idl = Idl.from_json(raw_json)
    return Program(idl, PROGRAM_ID, provider)

async def _close_provider(provider: Provider):
    await provider.connection.close()


def solana_initialize_material(material_id: str) -> str:
    async def _inner():
        provider = await _init_provider()
        program  = await _load_program(provider)
        seed     = [b'material', material_id.encode()]
        material_pda, _ = Pubkey.find_program_address(seed, PROGRAM_ID)
        sig = await program.rpc['initialize_material'](
            material_id,
            ctx={
                'accounts': {
                    'material': material_pda,
                    'authority': provider.wallet.public_key,
                    'system_program': SYS_PROGRAM_ID
                }
            }
        )
        await provider.connection.close()
        return sig
    return asyncio.run(_inner())


def solana_transfer_custody(material_id: str, from_holder: str, to_holder: str, sequence: int) -> str:
    async def _inner():
        provider = await _init_provider()
        program  = await _load_program(provider)
        seed     = [b'material', material_id.encode()]
        material_pda, _ = Pubkey.find_program_address(seed, PROGRAM_ID)
        sig = await program.rpc['transfer_custody'](
            material_id,
            sequence,
            to_holder,
            ctx={
                'accounts': {
                    'material': material_pda,
                    'authority': provider.wallet.public_key,
                }
            }
        )
        await provider.connection.close()
        return sig
    return asyncio.run(_inner())

# ─── Flask Routes ───────────────────────────────────────────────────────────

@app.route('/api/materials', methods=['GET'])
def list_materials():
    mats = list(materials_col.find({}, {'_id':0}))
    return jsonify(mats)

@app.route('/api/materials', methods=['POST'])
def create_material():
    data = request.get_json()
    material = {
        'materialId': data.get('materialId', f"Mat{int(materials_col.count_documents({}))+1}"),
        'description': data.get('description',''),
        'metadata': data.get('metadata', {}),
        'currentHolder': data.get('initialHolder',''),
        'status': 'In-Transit',
        'lastSequence': 0
    }
    materials_col.insert_one(material)
    solana_initialize_material(material['materialId'])
    return jsonify(material), 201

@app.route('/api/materials/<material_id>', methods=['GET'])
def get_material(material_id):
    mat = materials_col.find_one({'materialId':material_id},{'_id':0})
    if not mat:
        return jsonify({'error':'Not Found'}),404
    return jsonify(mat)

@app.route('/api/materials/<material_id>/transfers', methods=['GET'])
def list_transfers(material_id):
    txs = list(transfers_col.find({'materialId':material_id},{'_id':0}))
    return jsonify(txs)

@app.route('/api/materials/<material_id>/transfers', methods=['POST'])
def create_transfer(material_id):
    data = request.get_json()
    seq  = materials_col.find_one_and_update(
        {'materialId':material_id},
        {'$inc':{'lastSequence':1}},
        return_document=True
    )['lastSequence']
    tx = {
        'materialId': material_id,
        'sequence': seq,
        'from': data['from'],
        'to': data['to'],
        'timestamp': data.get('timestamp'),
        'notes': data.get('notes',''),
        'status': data.get('status','')
    }
    transfers_col.insert_one(tx)
    solana_transfer_custody(material_id, seq-1, tx['to']['name'], seq)
    return jsonify(tx),201

@app.route('/api/materials/<material_id>/status', methods=['GET'])
def get_status(material_id):
    mat = materials_col.find_one({'materialId':material_id},{'_id':0,'status':1})
    return jsonify({'status':mat['status']})

@app.route('/api/materials/<material_id>/quarantine', methods=['POST'])
def quarantine_material(material_id):
    materials_col.update_one({'materialId':material_id},{'$set':{'status':'Quarantined'}})
    return jsonify({'status':'Quarantined'})

@app.route('/api/signers', methods=['GET'])
def list_signers():
    s = list(signers_col.find({}, {'_id':0}))
    return jsonify(s)

@app.route('/api/signers', methods=['POST'])
def add_signer():
    data=request.get_json()
    signers_col.insert_one({'pubkey':data['pubkey'],'role':data.get('role','')})
    return jsonify(data),201

@app.route('/api/materials/<material_id>/export/csv', methods=['GET'])
def export_csv(material_id):
    txs = list(transfers_col.find({'materialId':material_id},{'_id':0}))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=txs[0].keys())
    writer.writeheader()
    writer.writerows(txs)
    return (output.getvalue(), {'Content-Type':'text/csv'})

@app.route('/api/materials/<material_id>/export/pdf', methods=['GET'])
def export_pdf(material_id):
    txs = list(transfers_col.find({'materialId':material_id},{'_id':0}))
    buffer = io.BytesIO()
    p = pdf_canvas.Canvas(buffer)
    y = 800
    for tx in txs:
        p.drawString(50, y, str(tx))
        y -= 20
    p.save()
    buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f"{material_id}_transfers.pdf")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=True)
