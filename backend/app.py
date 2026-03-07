@app.route("/whatsapp", methods=["POST"])
def whatsapp():

    incoming_msg = request.form.get("Body", "").strip()
    incoming_lower = incoming_msg.lower()

    raw_sender = request.form.get("From")
    sender = normalize_phone(raw_sender)

    print("MESSAGE RECEIVED:", incoming_msg)
    print("SENDER:", sender)

    resp = MessagingResponse()
    reply = resp.message()

    # ensure user session exists
    if sender not in user_sessions:
        user_sessions[sender] = {}

    session_data = user_sessions[sender]

    print("SESSION:", session_data)

    # =========================
    # START GENERAL COMPLAINT
    # =========================
    if incoming_lower in ["complaint", "start", "hi"]:

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

        if incoming_lower in ["yes", "y"]:
            session_data["anonymous"] = True

        elif incoming_lower in ["no", "n"]:
            session_data["anonymous"] = False

        else:
            reply.body("Please reply YES or NO")
            return str(resp)

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
    # SAVE COMPLAINT
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

        # notify HR
        if client and HR_WHATSAPP:

            try:

                client.messages.create(
                    from_="whatsapp:+14155238886",
                    to=HR_WHATSAPP,
                    body=f"""
🚨 New {new_complaint.complaint_type} Complaint

Message:
{complaint_text}

Company ID: {company_id}
"""
                )

            except Exception as e:
                print("HR notification failed:", e)

        reply.body("✅ Complaint submitted successfully.")

        user_sessions.pop(sender, None)

        return str(resp)

    # =========================
    # DEFAULT MESSAGE
    # =========================
    reply.body("""
Welcome to WeValYou.

To submit a complaint type:
complaint

For POSH harassment complaint type:
posh
""")

    return str(resp)