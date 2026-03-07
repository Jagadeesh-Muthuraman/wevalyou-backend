from flask import Flask, request, jsonify, session, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.security import generate_password_hash, check_password_hash
import os

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
HR_WHATSAPP = os.getenv("HR_WHATSAPP")

app = Flask(__name__)
app.secret_key = "wevalyou-secret-key"

CORS(app)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///wevalyou.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

from flask_migrate import Migrate
migrate = Migrate(app, db)

class HRUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship("Company", backref="hr_users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# =====================
# APP SETUP
# =====================


# =====================
# CONFIG
# =====================




client = None
if ACCOUNT_SID and AUTH_TOKEN:
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

# Map employee WhatsApp number → company_id

user_sessions = {}

# =====================
# MODELS
# =====================

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30), unique=True, nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    name = db.Column(db.String(100))

    company = db.relationship("Company", backref="employees")

class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    anonymous = db.Column(db.Boolean, default=True)
    sender = db.Column(db.String(50))
    status = db.Column(db.String(20), default="Open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    complaint_type = db.Column(db.String(20), default="GENERAL")  # GENERAL | POSH
    incident_date = db.Column(db.String(50))   # keep string for speed
    location = db.Column(db.String(100))

    company = db.relationship("Company", backref="complaints")

# =====================
# ROUTES
# =====================

@app.route("/")
def home():
    return "WeValYou backend is running"

@app.route("/test")
def test():
    return "TEST ROUTE WORKING"

# ---- Manual company onboarding (startup phase) ----
@app.route("/create_company")
def create_company():
    company = Company(name="Demo IT Company")
    db.session.add(company)
    db.session.commit()
    return f"Company created with ID: {company.id}"

# ---- HR Login ----
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        hr = HRUser.query.filter_by(email=email).first()

        if hr and hr.check_password(password):
            session["hr_logged_in"] = True
            session["hr_id"] = hr.id
            session["company_id"] = hr.company_id
            return redirect("/hr")

        return "Invalid credentials"

    return """
    <h2>HR Login</h2>
    <form method="post">
        Email: <input name="email"><br>
        Password: <input name="password" type="password"><br><br>
        <button type="submit">Login</button>
    </form>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---- HR Dashboard ----
@app.route("/hr")
def hr_dashboard():
    if not session.get("hr_logged_in"):
        return redirect("/login")

    company_id = session.get("company_id")

    complaints = Complaint.query.filter_by(
        company_id=company_id
    ).order_by(Complaint.created_at.desc()).all()

    html = """
    <h2>HR Dashboard – Complaints</h2>
    <a href="/logout">Logout</a><br><br>
    <table border="1" cellpadding="10">
        <tr>
            <th>ID</th>
            <th>Message</th>
            <th>Anonymous</th>
            <th>Sender</th>
            <th>Status</th>
            <th>Date</th>
        </tr>
    """

    for c in complaints:
        sender = "Hidden" if c.anonymous else c.sender
        html += f"""
        <tr>
            <td>{c.id}</td>
            <td>{c.message}</td>
            <td>{c.anonymous}</td>
            <td>{sender}</td>
            <td>{c.status}</td>
            <td>{c.created_at}</td>
        </tr>
        """

    html += "</table>"
    return html

# ---- WhatsApp Bot ----
@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    incoming_lower = incoming_msg.lower()
    sender = request.form.get("From")
    print("WHATSAPP SENDER:", sender)

    resp = MessagingResponse()
    reply = resp.message()

    # Create session if new user
    if sender not in user_sessions:
        user_sessions[sender] = {}

    session_data = user_sessions[sender]

    # =========================
    # START GENERAL COMPLAINT
    # =========================
    if incoming_lower == "complaint":
        session_data.clear()
        session_data["complaint_type"] = "GENERAL"
        session_data["step"] = "ask_anonymous"

        reply.body("Do you want to stay anonymous? Reply YES or NO")
        return str(resp)

    # =========================
    # START POSH COMPLAINT
    # =========================
    if incoming_lower == "posh":
        session_data.clear()
        session_data["complaint_type"] = "POSH"
        session_data["step"] = "ask_anonymous"

        reply.body("🚨 POSH Complaint Started.\nDo you want to stay anonymous? Reply YES or NO")
        return str(resp)

    # =========================
    # ASK ANONYMOUS
    # =========================
    if session_data.get("step") == "ask_anonymous":

        if incoming_lower == "yes":
            session_data["anonymous"] = True
        elif incoming_lower == "no":
            session_data["anonymous"] = False
        else:
            reply.body("Please reply YES or NO")
            return str(resp)

        # Decide next step
        if session_data["complaint_type"] == "POSH":
            session_data["step"] = "get_date"
            reply.body("Enter incident date (DD/MM/YYYY)")
        else:
            session_data["step"] = "get_message"
            reply.body("Please type your complaint")

        return str(resp)

    # =========================
    # POSH DATE
    # =========================
    if session_data.get("step") == "get_date":
        session_data["incident_date"] = incoming_msg
        session_data["step"] = "get_location"

        reply.body("Enter incident location")
        return str(resp)

    # =========================
    # POSH LOCATION
    # =========================
    if session_data.get("step") == "get_location":
        session_data["location"] = incoming_msg
        session_data["step"] = "get_message"

        reply.body("Please describe the incident")
        return str(resp)

    # =========================
    # FINAL MESSAGE SAVE
    # =========================
    if session_data.get("step") == "get_message":

        complaint_text = incoming_msg

        employee = Employee.query.filter_by(phone=sender).first()

        if not employee:
            reply.body("Your number is not registered with any company HR.")
            return str(resp)

        company_id = employee.company_id
        new_complaint = Complaint(
            company_id=company_id,
            message=complaint_text,
            anonymous=session_data.get("anonymous", True),
            sender=None if session_data.get("anonymous") else sender,
            complaint_type=session_data.get("complaint_type", "GENERAL"),
            incident_date=session_data.get("incident_date"),
            location=session_data.get("location"),
            status="Open"
        )

        db.session.add(new_complaint)
        db.session.commit()

        # Notify HR
        if client and HR_WHATSAPP:
            try:
                client.messages.create(
                    from_="whatsapp:+14155238886",
                    to=HR_WHATSAPP,
                    body=f"🚨 New {new_complaint.complaint_type} Complaint:\n\n{complaint_text}"
                )
            except Exception as e:
                print("HR notification failed:", e)

        reply.body("✅ Complaint submitted successfully.")
        user_sessions.pop(sender, None)

        return str(resp)

    # =========================
    # DEFAULT MESSAGE
    # =========================
    reply.body("Type 'complaint' or 'posh' to start.")
    return str(resp)

# ---- Web / App API ----
@app.route("/complaint", methods=["POST"])
def complaint():
    data = request.json

    company_id = data.get("company_id")
    message = data.get("message")
    anonymous = data.get("anonymous", True)
    sender = data.get("sender")

    if not company_id or not message:
        return jsonify({"error": "company_id and message required"}), 400

    new_complaint = Complaint(
        company_id=company_id,
        message=message,
        anonymous=anonymous,
        sender=sender if not anonymous else None
    )

    db.session.add(new_complaint)
    db.session.commit()

    return jsonify({
        "status": "success",
        "complaint_id": new_complaint.id
    }), 201


@app.route("/setup")
def setup():
    sender = "whatsapp:+91YOURNUMBER"  # replace once

    company = Company.query.first()
    if not company:
        company = Company(name="Demo IT Company")
        db.session.add(company)
        db.session.commit()

    existing = Employee.query.filter_by(phone=sender).first()
    if not existing:
        employee = Employee(
            phone=sender,
            company_id=company.id,
            name="Test Employee"
        )
        db.session.add(employee)
        db.session.commit()

    return "Setup complete"

# =====================
# RUN
# =====================

@app.route("/create_hr")
def create_hr():
    company = Company.query.first()
    if not company:
        return "Create company first"

    hr = HRUser(
        email="hr@demo.com",
        company_id=company.id
    )
    hr.set_password("hr123")

    db.session.add(hr)
    db.session.commit()

    return "HR user created: hr@demo.com / hr123"

@app.route("/register_employee")
def register_employee():
    phone = request.args.get("phone")

    company = Company.query.first()
    if not company:
        company = Company(name="Default Company")
        db.session.add(company)
        db.session.commit()

    existing = Employee.query.filter_by(phone=phone).first()
    if existing:
        return "Employee already exists"

    emp = Employee(phone=phone, company_id=company.id)
    db.session.add(emp)
    db.session.commit()

    return "Employee registered"

# ✅ Ensure database tables exist on startup (Render compatible)
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)