# BoldSign Check-In/Out Demo

A Python script to streamline employee check-in and check-out using the BoldSign API. Built for Syncfusion, this demo creates a reusable form for employees to sign in (e.g., "09:00 AM") and out (e.g., "05:00 PM") daily, with data synced to HR via webhooks. Perfect for eliminating morning queues and saving check-in & check-out time.

# 🚀 Features

Check-In & Check-Out: One form captures time_in and time_out with employee name, ID, date, and signature.

BoldSign Integration: Creates templates, signing URLs, and webhooks via the API.

Secure Config: Uses .env for API token and base URL.

Demo-Ready: Generates URLs in seconds for a slick 30-second pitch.

Error Handling: Catches issues like 401 Unauthorized or 500 Server Error.


# 📋 Prerequisites

Python 3.8+
BoldSign sandbox account (free API token)
Git (to clone and commit)


# ⚙️ Setup

## Clone the Repo

`git clone https://github.com/your-username/boldsign-checkinout-demo.git`
`cd boldsign-checkinout-demo`


## Set Up Virtual Environment

`python -m venv venv`
`source venv/bin/activate  # Linux/Mac`
`.\venv\Scripts\activate   # Windows`


## Install Dependencies

`pip install requests python-dotenv`


## Configure Environment
Create a .env file:
`touch .env  # Linux/Mac`
`echo.>.env  # Windows (CMD)`

Add your BoldSign sandbox token and API URL:
`BOLDSIGN_API_TOKEN=your_sandbox_token`
`BOLDSIGN_BASE_URL=https://api.boldsign.com/v1`


Get your token from BoldSign API Tokens.
.env is gitignored for security.




# 🛠️ Usage

## Run the Script
`python checkin_out.py`


## Output

Expect:
`Using BASE_URL: https://api.boldsign.com/v1`

`API_TOKEN (first 5 chars): xyz12...`

`Signing URL: https://app.boldsign.com/link/...`

`Signing URL: https://app.boldsign.com/link/...`

`Webhook ID: wh_123`


## Test the Form

Copy a Signing URL.

Paste into a browser (e.g., Chrome).

Verify fields:
Pre-filled: name (e.g., "Kevin Omondi"), employee_id (e.g., "SFK000"), date (e.g., "2025-04-16").

Editable: time_in, time_out, signature.


Check-in: Enter time_in (e.g., "09:00 AM"), sign, submit.

Check-out: Reopen URL, enter time_out (e.g., "05:00 PM"), sign, submit.


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

