# Biometric Attendance System 🕒

A Flask-based web application for managing employee attendance using biometric (fingerprint) scans. Designed for any organization, this system offers real-time check-in/check-out tracking, user management for multiple admins, and a customizable interface.

## Features ✨

### Biometric Attendance:

 Record employee check-ins and check-outs with fingerprint scans, stored securely in an SQLite database.

### User Management:

 Admins can add, edit, or delete user accounts for HR staff, with secure JWT authentication.
Daily Auto-Refresh: Attendance records display only today’s data, refreshing automatically every 60 seconds.

### Employee Management:

 Add, edit, search, or bulk delete employees via a web interface.

### Customizable Branding: 

Configure company name, logo, and colors via config.json.

### Real-Time Updates:

 WebSocket integration for instant attendance updates.

### Export Data:

 Download attendance records as CSV files.

### Audit Logging:

 Track biometric scan actions for accountability.

### Secure Authentication: 

Password hashing with bcrypt and encrypted fingerprint storage.

## Prerequisites 📋

Python 3.8+ (3.10 or 3.11 recommended)
A biometric scanner (compatible fingerprint templates required)
SQLite (included with Python)

## Installation 🚀

### Clone the Repository:

`git clone https://github.com/yourusername/biometric-attendance-system.git`
`cd biometric-attendance-system`


### Set Up Virtual Environment:

`python -m venv venv`
`source venv/bin/activate  # On Windows: venv\Scripts\activate`


### Install Dependencies:

`pip install -r requirements.txt`


### Configure Environment:

Create a .env file in the root directory:
```
FLASK_SECRET_KEY=your-secret-key
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
JWT_SECRET_KEY=your-jwt-secret-key

```

### Customize Branding:

Edit config.json to set company details:

```
{
    "company_name": " Your Organization",
    "logo_url": "/static/photos/logo.png",
    "theme": {
        "primary_color": "#007bff",
        "secondary_color": "#6c757d"
    },
    "max_cycles_per_day": 2,
    "timezone": "Africa/Nairobi"
}
```

Place your logo in `static/` if using a custom `logo_url`.


### Run the Application:
`python app.py`


Access at `http://localhost:5000`.



## Usage 🖥️

### Login: 

Use default credentials (`admin/admin123`) to access the dashboard.

### Manage Users:

 Navigate to "Manage Users" to add/edit/delete admin accounts (min 8-character passwords).

### Manage Employees:

 Add employees with IDs (e.g., `EMP001`), names, and fingerprint templates.

### Track Attendance:

 Use a biometric scanner to send fingerprint templates via `POST /biometric_scan`. Records auto-refresh daily.

### Export Data:

 Click "Export CSV" to download attendance records.

### Customize:

 Update `config.json` for branding or cycle limits.

## Project Structure 📂
```
biometric-attendance-system/
├── app.py                 # Main Flask application
├── config.json            # Branding and configuration
├── data/
│   └── biometric_attendance.db  # SQLite database
├── static/                # Logos and exported CSVs
├── templates/
│   ├── dashboard.html     # Main dashboard
│   └── users.html         # User management interface
├── .env                   # Environment variables
├── requirements.txt       # Dependencies
└── README.md              # This file
```
## Database Schema 🗄️

employees: `employee_id` (PK), `name`, `fingerprint_template`
attendance: `timestamp`, `employee_id` (FK), `name`, `date`, `time_in`, `time_out`, `fingerprint`
audit_log: `timestamp`, `employee_id` (FK), `action`
users: `username` (PK), `password_hash`

## Security 🔒

Passwords are hashed with `bcrypt`.
Fingerprints are encrypted using `cryptography.fernet`.
JWT tokens secure API endpoints.
Default admin user is protected from deletion.

## Troubleshooting 🛠️

Bcrypt Error: Ensure `bcrypt==4.0.1` and `passlib==1.7.4`:

`pip install bcrypt==4.0.1 passlib==1.7.4`


Port Conflict:
`netstat -ano | findstr :5000`
`taskkill /PID <pid> /F`


Database Issues:
```
python -c "import sqlite3; 
conn = sqlite3.connect('data/biometric_attendance.db'); 
cursor = conn.cursor(); cursor.execute('SELECT name FROM sqlite_master WHERE type=\"table\"'); 
print(cursor.fetchall()); conn.close()"
```

Check logs in the terminal or browser console (F12).

## Contributing 🤝

Contributions are welcome! Please:

Fork the repo.
Create a feature branch (`git checkout -b feature/xyz`).
Commit changes (`git commit -m "Add xyz"`).
Push to the branch (`git push origin feature/xyz`).
Open a pull request.

## License 📜

MIT License. See `LICENSE` for details.

## Contact 📬

For support or inquiries, contact `kevojr69@gmail.com` or open an issue on GitHub.

Built by `Kevin Omondi Jr`.
