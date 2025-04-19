from flask import Flask, jsonify, request

app = Flask(__name__)

# ─── Sample Data ───────────────────────────────────────────────────────────────

materials = [
    {
        "materialId": "MatA123",
        "description": "Cobalt-60 source, 5 Ci",
        "metadata": {"hazardClass": "7", "batch": "A123"},
        "currentHolder": "ABC_Chemicals",
        "status": "In-Transit",
        "lastSequence": 2
    }
]

transfers = {
    "MatA123": [
        {
            "sequence": 1,
            "from": {"name": "ABC_Chemicals", "location": {"lat": 34.05, "lng": -118.25}},
            "to":   {"name": "TransSafe_Logistics", "location": {"lat": 36.17, "lng": -115.14}},
            "timestamp": 1713600000,
            "notes": "Loaded onto truck, temp 4 °C",
            "status": "Delivered"
        },
        {
            "sequence": 2,
            "from": {"name": "TransSafe_Logistics", "location": {"lat": 36.17, "lng": -115.14}},
            "to":   {"name": "Regional_Lab", "location": {"lat": 33.45, "lng": -112.07}},
            "timestamp": 1713686400,
            "notes": "Arrived, chain intact",
            "status": "In-Transit"
        }
    ]
}

signers = [
    {"pubkey": "Signer1PubKey", "role": "transporter"},
    {"pubkey": "Signer2PubKey", "role": "lab_receiver"}
]

# ─── Authentication ──────────────────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def login():
    # static token for front‑end use
    return jsonify({"token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sample"}), 200

# ─── Users (RBAC stub) ──────────────────────────────────────────────────────

@app.route("/api/users", methods=["GET"])
def list_users():
    return jsonify([
        {"userId": "1", "username": "alice", "role": "manufacturer"},
        {"userId": "2", "username": "bob",   "role": "transporter"},
    ])

# ─── Materials ──────────────────────────────────────────────────────────────

@app.route("/api/materials", methods=["GET"])
def get_materials():
    return jsonify(materials)

@app.route("/api/materials", methods=["POST"])
def create_material():
    payload = request.json
    new = {
        "materialId": "MatX999",
        "description": payload.get("description"),
        "metadata": payload.get("metadata", {}),
        "currentHolder": payload.get("initialHolder"),
        "status": "In-Transit",
        "lastSequence": 0
    }
    materials.append(new)
    return jsonify(new), 201

@app.route("/api/materials/<material_id>", methods=["GET"])
def get_material(material_id):
    mat = next((m for m in materials if m["materialId"] == material_id), None)
    if not mat:
        return jsonify({"error": "Not found"}), 404
    return jsonify(mat)

# ─── Custody Transfers ───────────────────────────────────────────────────────

@app.route("/api/materials/<material_id>/transfers", methods=["GET"])
def list_transfers(material_id):
    return jsonify(transfers.get(material_id, []))

@app.route("/api/materials/<material_id>/transfers", methods=["POST"])
def add_transfer(material_id):
    payload = request.json
    seq_list = transfers.setdefault(material_id, [])
    new_seq = len(seq_list) + 1
    entry = {
        "sequence": new_seq,
        "from": payload["from"],
        "to": payload["to"],
        "timestamp": payload.get("timestamp", 1713772800),
        "notes": payload.get("notes", ""),
        "status": payload.get("status", "In-Transit")
    }
    seq_list.append(entry)
    # update material master record
    for m in materials:
        if m["materialId"] == material_id:
            m["currentHolder"] = payload["to"]["name"]
            m["lastSequence"] = new_seq
            break
    return jsonify(entry), 201

# ─── Quarantine & Status ────────────────────────────────────────────────────

@app.route("/api/materials/<material_id>/status", methods=["GET"])
def get_status(material_id):
    mat = next((m for m in materials if m["materialId"] == material_id), None)
    return jsonify({"status": mat["status"]}) if mat else ({"error": "Not found"}, 404)

@app.route("/api/materials/<material_id>/quarantine", methods=["POST"])
def quarantine(material_id):
    mat = next((m for m in materials if m["materialId"] == material_id), None)
    if not mat:
        return jsonify({"error": "Not found"}), 404
    mat["status"] = "Quarantined"
    return jsonify({"materialId": material_id, "status": "Quarantined"}), 200

# ─── Signers ────────────────────────────────────────────────────────────────

@app.route("/api/signers", methods=["GET"])
def list_signers():
    return jsonify(signers)

@app.route("/api/signers", methods=["POST"])
def add_signer():
    payload = request.json
    signers.append({"pubkey": payload["pubkey"], "role": payload["role"]})
    return jsonify(signers[-1]), 201

# ─── Reporting ─────────────────────────────────────────────────────────────

@app.route("/api/materials/<material_id>/export/csv", methods=["GET"])
def export_csv(material_id):
    # stub URL for front-end; implement real export later
    return jsonify({"url": f"/downloads/{material_id}.csv"}), 200

@app.route("/api/materials/<material_id>/export/pdf", methods=["GET"])
def export_pdf(material_id):
    return jsonify({"url": f"/downloads/{material_id}.pdf"}), 200

# ─── Run App ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=8888)
