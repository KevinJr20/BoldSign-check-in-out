# Biometric Check-In Demo

A Python-based system to enhance Syncfusion's biometric check-in process, addressing manual signing inefficiencies. It features fast check-ins (<10 seconds), a real-time HR dashboard, and compliance with Kenyan labor law (Employment Act, 2007).

## 🚀 Features

- **Fast Check-Ins**: <10-second biometric scans (fingerprint, face).
- **HR Dashboard**: Real-time attendance logs, exportable to CSV.
- **Compliance**: Encrypted data, e-signed consents via BoldSign.
- **Accuracy**: Prevents buddy punching with strict biometric verification.
- **Employee-Friendly**: Mobile app endpoint, facial recognition fallback.

## 📋 Prerequisites

- Python 3.8+
- SQLite (included)
- BoldSign account (for consent forms)

## ⚙️ Setup

1. **Clone the Repo**

   ```bash
   git clone https://github.com/your-username/biometric-checkin-demo.git
   cd biometric-checkin-demo


## Set Up Virtual Environment

`python -m venv venv`
`source venv/bin/activate  # Linux/Mac`
`.\venv\Scripts\activate   # Windows`


## Install Dependencies

`pip install -r requirements.txt`


## Configure Environment
Create a .env file:
`echo ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") > .env`
`echo FLASK_ENV=development >> .env  # Windows (CMD)`

Add your BoldSign sandbox token and API URL:
`BOLDSIGN_API_TOKEN=your_sandbox_token`
`BOLDSIGN_BASE_URL=https://api.boldsign.com/v1`


Get your token from BoldSign API Tokens.
.env is gitignored for security.

## Initialize Database

Run `app.py` to create `biometric_attendance.db`:

`python app.py`


# 🛠️ Usage

## Run the App
`python app.py`

## Access Dashboard

Open `http://localhost:5000` in Chrome to view HR logs.


## Test Check-In

Simulate biometric check-in:

`curl -X POST http://localhost:5000/checkin -d "employee_id=EMP123&name=Kevin%20Omondi&time_in=08:00%20AM"`


## Test the Form

Copy a Signing URL.

Paste into a browser (e.g., Chrome).

Verify fields:
Pre-filled: name (e.g., "Kevin Omondi"), employee_id (e.g., "SFK000"), date (e.g., "2025-04-16").

Editable: time_in, time_out, signature.


Check-in: Enter time_in (e.g., "09:00 AM"), sign, submit.

Check-out: Reopen URL, enter time_out (e.g., "05:00 PM"), sign, submit.


## Upload Consent Form

Import `consent_form.md` to BoldSign.

Send to employees for e-signing.

# 📂 Project Structure

boldsign-checkinout-demo/
├── .env              # API token and URL (gitignored)
├── .gitignore        # Ignores .env, venv, etc.
├── checkin_out.py    # Main script
├── README.md         # This file
└── venv/             # Virtual environment


# 🐞 Troubleshooting

## 401 Unauthorized:

Check `BOLDSIGN_API_TOKEN` in `.env.`
Regenerate at BoldSign API Tokens.


## 500 Server Error:

Verify `BOLDSIGN_BASE_URL=https://api.boldsign.com/v1.`
Retry or contact BoldSign support.


## Missing Fields:

Ensure `checkin_out.py` matches the latest version (includes `time_in`, `time_out`).


## No Output:

Confirm `requests`, `python-dotenv` installed (`pip list`).
Reactivate venv: `.\venv\Scripts\activate` (Windows).


# 🤝 Contributing

Fork the repo.
Create a branch: `git checkout -b feature-name`.
Commit changes: `git commit -m "Add feature-name"`.
Push: `git push origin feature-name`.
Open a pull request.


# 📜 License

MIT License. See `LICENSE` for details.

# 🙌 Acknowledgments

BoldSign for the robust API.

Syncfusion for the inspiration.

`Kevin Ochieng Omondi Jr.` for coding this demo!

