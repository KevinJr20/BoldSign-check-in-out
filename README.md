Hospitality Management System 🕒🏨
A Flask-based web application for managing employee attendance, hotel bookings, and guest records. Designed for organizations in the hospitality industry, this system offers biometric check-in/check-out tracking, room management, guest check-in/out, and a customizable interface with real-time updates and Redis caching for performance.
Features ✨
Biometric Attendance

Record employee check-ins and check-outs with fingerprint scans, securely stored in a PostgreSQL database.
Daily auto-refresh of attendance records with pagination support (50 records per page by default).

Hotel Booking

Book rooms with guest details, check-in/check-out dates, and room type selection (e.g., standard, deluxe, suite).
Real-time room availability checking via a web interface.

Guest Management

Manage guest check-ins and check-outs with real-time status updates.
View paginated guest records with details like room assignments and stay duration.

User Management

Admins can add, edit, or delete user accounts for HR staff and employees, with secure JWT authentication.
Role-based access (admin, employee, guest) for dashboard features.

Employee Management

Add, edit, search, or bulk delete employees via a web interface, including fingerprint templates.

Customizable Branding

Configure company name, logo, and colors via config.json.

Real-Time Updates

SocketIO integration for instant updates on attendance, guest, and room status changes.

Data Export

Download attendance records as CSV files for reporting.

Audit Logging

Track biometric scan and user actions for accountability.

Performance Optimization

Redis caching for frequent database queries (attendance, rooms, guests) with 5-minute TTL.
Paginated data loading for efficient dashboard rendering.

Secure Authentication

Password hashing with bcrypt and encrypted fingerprint storage using cryptography.fernet.
JWT tokens secure API endpoints with role-based authorization.

Prerequisites 📋

Python: 3.8+ (3.10 or 3.11 recommended)
PostgreSQL: 12+ for data storage
Redis: 6+ for caching (local or cloud-hosted, e.g., Redis Labs)
Biometric Scanner: Compatible fingerprint templates required
Node.js: For SocketIO client (optional, included via CDN in templates)
Dependencies: Listed in requirements.txt

Installation 🚀
1. Clone the Repository
git clone https://github.com/yourusername/hospitality-management-system.git
cd hospitality-management-system

2. Set Up Virtual Environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

3. Install Dependencies
pip install -r requirements.txt

4. Set Up PostgreSQL

Install PostgreSQL (e.g., via apt, brew, or Docker):# Ubuntu
sudo apt-get install postgresql postgresql-contrib
# macOS
brew install postgresql
# Docker
docker run -d --name postgres -p 5432:5432 -e POSTGRES_PASSWORD=your_password postgres


Create a database:psql -U postgres
CREATE DATABASE hospitality;
\q


Initialize tables (run provided SQL script or migrations):psql -U postgres -d hospitality -f init_db.sql



5. Set Up Redis

Local Redis:# Docker
docker run -d --name redis -p 6379:6379 redis:latest
# Ubuntu
sudo apt-get install redis-server
sudo systemctl enable redis
sudo systemctl start redis
# macOS
brew install redis
brew services start redis


Redis Labs (cloud):
Sign up at redis.com.
Create a database and note the endpoint and password.


Test Redis:redis-cli ping  # Should return PONG



6. Configure Environment
Create a .env file in the root directory:
FLASK_SECRET_KEY=your-secret-key
JWT_SECRET_KEY=your-jwt-secret-key
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
DATABASE_URL=postgresql://user:password@localhost:5432/hospitality
REDIS_URL=redis://localhost:6379/0  # Local Redis
# REDIS_URL=rediss://:your_password@redis-12345.c123.us-east-1-1.ec2.cloud.redislabs.com:12345/0  # Redis Labs
SENTRY_DSN=your-sentry-dsn

7. Customize Branding
Edit config.json to set company details:
{
    "company_name": "Your Organization",
    "logo_url": "/static/photos/logo.png",
    "theme": {
        "primary_color": "#007bff",
        "secondary_color": "#6c757d"
    },
    "max_cycles_per_day": 2,
    "timezone": "Africa/Nairobi"
}

Place your logo in static/photos/ if using a custom logo_url.
8. Run the Application
python app.py

Access at http://localhost:5000.
Usage 🖥️
Login

Use default credentials (admin/admin123) to access the dashboard.
Roles: admin (full access), employee (attendance only), guest (booking and guest records).

Manage Users

Navigate to "Manage Users" to add/edit/delete admin accounts (minimum 8-character passwords).

Manage Employees

Add employees with IDs (e.g., EMP001), names, and fingerprint templates via "Employee Management".

Track Attendance

Use a biometric scanner to send fingerprint templates via POST /biometric_scan.
View paginated attendance records, auto-refreshed every 60 seconds.

Book Rooms

Access "Hotel Booking" tab to enter guest details, select room type, and check availability.
Confirm bookings and view updated room statuses.

Manage Guests

Use "Guest Management" tab to check guests in/out and view paginated guest records.
Sync with external channels (e.g., OTAs) via the sync button (admin only).

Export Data

Click "Export CSV" in the attendance section to download records.

Customize

Update config.json for branding, cycle limits, or timezone.

```
Project Structure 📂
hospitality-management-system/
├── app.py                 # Main Flask application
├── config.json            # Branding and configuration
├── static/                # Static assets
│   ├── photos/            # Logos and images
│   └── exports/           # Exported CSVs
├── templates/             # HTML templates
│   ├── base.html          # Base template
│   ├── dashboard.html     # Main dashboard with tabs
│   └── users.html         # User management interface
├── init_db.sql            # PostgreSQL schema initialization
├── .env                   # Environment variables
├── requirements.txt       # Dependencies
└── README.md              # This file
```

Database Schema 🗄️

employees: employee_id (PK), name, fingerprint_template
attendance: id (PK), employee_id (FK), name, date, time_in, time_out, timestamp, fingerprint
rooms: room_id (PK), room_type, status
guests: guest_id (PK), name, room_id (FK), check_in_date, check_out_date, status
audit_log: id (PK), timestamp, employee_id (FK), action
users: username (PK), password_hash, role

Security 🔒

Passwords hashed with bcrypt.
Fingerprints encrypted using cryptography.fernet.
JWT tokens secure API endpoints with role-based access.
Redis connections secured with passwords (local) or TLS (cloud).
Default admin user protected from deletion.

Troubleshooting 🛠️
Bcrypt Error
Ensure correct versions:
pip install bcrypt==4.0.1 passlib==1.7.4

Port Conflict
Check and kill conflicting processes:
netstat -ano | findstr :5000  # Windows
lsof -i :5000                 # Linux/macOS
taskkill /PID <pid> /F       # Windows
kill -9 <pid>                # Linux/macOS

PostgreSQL Issues
Verify database connection:
psql -U user -d hospitality -c "\dt"

Check DATABASE_URL in .env.
Redis Issues
Test connection:
redis-cli ping  # Should return PONG

Ensure REDIS_URL is correct and Redis is running.
Database Schema Issues
Reinitialize tables:
psql -U user -d hospitality -f init_db.sql

Check logs in the terminal or browser console (F12).

## Contributing 🤝

Contributions are welcome! Please:

## Fork the repo.

Create a feature branch (git checkout -b feature/xyz).
Commit changes (git commit -m "Add xyz").
Push to the branch (git push origin feature/xyz).
Open a pull request.

## License 📜

MIT License. See `LICENSE` for details.
Contact 📬
For support or inquiries, contact `kevojr69@gmail.com` or open an issue on GitHub.
Built by `Kevin Omondi Jr.`
