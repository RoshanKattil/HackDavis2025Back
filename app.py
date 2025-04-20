from flask import Flask, jsonify, request
from pymongo import MongoClient, ASCENDING
import os, json, asyncio
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
# System program ID (native): all 1s
SYS_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
from anchorpy import Program, Provider, Wallet

# ─── Configuration ─────────────────────────────────────────────────────────
MONGO_URI       = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME         = os.getenv("DB_NAME", "chain_of_custody")
SOLANA_RPC_URL  = os.getenv("SOLANA_RPC_URL", "http://127.0.0.1:8899")
PROGRAM_ID      = Pubkey.from_string(os.getenv("PROGRAM_ID", "8ZKteuY8Ro67u6G9ySTmNA1URo9KFjAS6iPoNQKBjrDN"))
AUTHORITY_KEY   = os.getenv("AUTHORITY_KEYPAIR", "~/.config/solana/id.json")
ANCHOR_IDL_PATH = os.getenv("ANCHOR_IDL_PATH", "/Users/lalkattil/Desktop/DavisHacks2025/chain_custody/target/idl/chain_custody.json")


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
    """
    Load a keypair from file, or generate and save a new one if none exists.
    """
    real_path = os.path.expanduser(path)
    # If file missing, generate new keypair and save it
    if not os.path.exists(real_path):
        print(f"Keypair file not found at {real_path}, generating a new one...")
        kp = Keypair.generate()
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        with open(real_path, 'w') as f:
            # store secret key as list of ints
            json.dump(list(kp.to_bytes()), f)
        return kp
    # Otherwise load existing
    with open(real_path, 'r') as f:
        data = json.load(f)
    return Keypair.from_bytes(bytes(data))

async def _init_provider():
    client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
    auth   = load_local_keypair(AUTHORITY_KEY)
    wallet = Wallet(auth)
    return Provider(client, wallet)

async def _load_program(provider: Provider) -> Program:
    """
    Load the Anchor program by reading the IDL JSON and instantiating Program.
    """
    # Read IDL from file
    from anchorpy import Idl
    from pathlib import Path
    idl_data = json.loads(Path(ANCHOR_IDL_PATH).read_text())
    idl = Idl.from_json(idl_data)
    # Instantiate the program client
    return Program(idl, PROGRAM_ID, provider)


def solana_initialize_material(material_id: str):
    async def _inner():
        provider = await _init_provider()
        program  = await _load_program(provider)
        # derive PDA
        seed          = [b"material", material_id.encode()]
        material_pda, _ = Pubkey.find_program_address(seed, PROGRAM_ID)
        sig = await program.rpc["initialize_material"](
            material_id,
            ctx={
                "accounts": {
                    "materialAccount": material_pda,
                    "initializer":      provider.wallet.public_key,
                    "systemProgram":    SYS_PROGRAM_ID,
                }
            }
        )
        await provider.connection.close()
        return sig
    return asyncio.run(_inner())


def solana_transfer_custody(material_id: str, from_holder: str, to_holder: str, sequence: int):
    async def _inner():
        provider = await _init_provider()
        program  = await _load_program(provider)
        seed          = [b"material", material_id.encode()]
        material_pda, _ = Pubkey.find_program_address(seed, PROGRAM_ID)
        new_holder_pk  = Pubkey.from_string(to_holder)
        sig = await program.rpc["transfer_material"](
            new_holder_pk,
            ctx={
                "accounts": {
                    "materialAccount": material_pda,
                    "currentHolder":   provider.wallet.public_key,
                }
            }
        )
        await provider.connection.close()
        return sig
    return asyncio.run(_inner())

# ─── Flask App ──────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/api/auth/login", methods=["POST"])
def login():
    return jsonify({"token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sample"}), 200

# ─── Materials Endpoints ────────────────────────────────────────────────────
@app.route("/api/materials", methods=["GET"])
def get_materials():
    docs = list(materials_col.find({}, {"_id": 0}))
    return jsonify(docs), 200

@app.route("/api/materials", methods=["POST"])
def create_material():
    data = request.json or {}
    material = {
        "materialId":    data.get("materialId", "Mat" + str(materials_col.count_documents({})+1)),
        "description":   data.get("description", ""),
        "metadata":      data.get("metadata", {}),
        "currentHolder": data.get("initialHolder", ""),
        "status":        "In-Transit",
        "lastSequence":  0
    }
    materials_col.insert_one(material)
    solana_initialize_material(material["materialId"])
    return jsonify(material), 201

@app.route("/api/materials/<material_id>", methods=["GET"])
def get_material(material_id: str):
    mat = materials_col.find_one({"materialId": material_id}, {"_id": 0})
    if not mat:
        return jsonify({"error": "Not found"}), 404
    return jsonify(mat), 200

# ─── Transfers Endpoints ────────────────────────────────────────────────────
@app.route("/api/materials/<material_id>/transfers", methods=["GET"])
def list_transfers(material_id: str):
    txs = list(transfers_col.find({"materialId": material_id}, {"_id": 0}).sort("sequence", ASCENDING))
    return jsonify(txs), 200

@app.route("/api/materials/<material_id>/transfers", methods=["POST"])
def add_transfer(material_id: str):
    data = request.json or {}
    mat  = materials_col.find_one({"materialId": material_id}, {"lastSequence": 1})
    next_seq = mat["lastSequence"] + 1 if mat else 1
    entry = {
        "materialId": material_id,
        "sequence":   next_seq,
        "from":       data.get("from", {}),
        "to":         data.get("to", {}),
        "timestamp":  data.get("timestamp"),
        "notes":      data.get("notes", ""),
        "status":     data.get("status", "In-Transit")
    }
    transfers_col.insert_one(entry)
    materials_col.update_one({"materialId": material_id}, {"$set": {"currentHolder": entry["to"].get("name", ""), "lastSequence": next_seq}})
    solana_transfer_custody(material_id, entry["from"].get("name", ""), entry["to"].get("name", ""), next_seq)
    return jsonify(entry), 201

# ─── Status & Quarantine ────────────────────────────────────────────────────
@app.route("/api/materials/<material_id>/status", methods=["GET"])
def get_status(material_id: str):
    mat = materials_col.find_one({"materialId": material_id}, {"status": 1, "_id": 0})
    if not mat:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": mat["status"]}), 200

@app.route("/api/materials/<material_id>/quarantine", methods=["POST"])
def quarantine(material_id: str):
    result = materials_col.update_one({"materialId": material_id}, {"$set": {"status": "Quarantined"}})
    if result.matched_count == 0:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"materialId": material_id, "status": "Quarantined"}), 200

# ─── Signers Endpoints ─────────────────────────────────────────────────────
@app.route("/api/signers", methods=["GET"])
def list_signers():
    docs = list(signers_col.find({}, {"_id": 0}))
    return jsonify(docs), 200

@app.route("/api/signers", methods=["POST"])
def add_signer():
    data = request.json or {}
    signer = {"pubkey": data.get("pubkey"), "role": data.get("role", "")} 
    signers_col.insert_one(signer)
    return jsonify(signer), 201

# ─── Reporting / Exports ────────────────────────────────────────────────────
@app.route("/api/materials/<material_id>/export/csv", methods=["GET"])
def export_csv(material_id: str):
    return jsonify({"url": f"/downloads/{material_id}.csv"}), 200

@app.route("/api/materials/<material_id>/export/pdf", methods=["GET"])
def export_pdf(material_id: str):
    return jsonify({"url": f"/downloads/{material_id}.pdf"}), 200

# ─── Run App ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8888)
