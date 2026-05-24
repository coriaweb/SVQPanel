# SVQPanel Testing Guide

## What's Completed

### Phase 1 ✅ - API Structure
- Database models for Users, Domains, SSL, IPv6
- SQLAlchemy ORM setup with PostgreSQL
- Pydantic schemas for validation

### Phase 2 ✅ - API Endpoints (17 endpoints)
- Users: POST, GET all, GET by ID, PUT, DELETE
- Domains: POST, GET all, GET by ID, PUT, DELETE
- PHP: GET versions, PUT change version
- SSL: POST create, GET status, DELETE revoke
- IPv6: POST assign, GET status, DELETE remove

### Phase 3 ✅ - System Scripts
- `UserManager`: Create/delete system users with /home directories
- `DomainManager`: Create Nginx vhosts, manage directories, change PHP versions
- `PHPManager`: Detect installed PHP versions, restart PHP-FPM
- `SSLManager`: Create/revoke certificates with certbot
- `IPv6Manager`: Assign/remove IPv6 addresses to network interfaces

### Phase 4 ✅ - Vue 3 Frontend
- Components:
  - `Modal.vue`: Reusable modal dialog
  - `UserForm.vue`: Create/edit users
  - `DomainForm.vue`: Create/edit domains
  - `SSLManager.vue`: Certificate management
  - `IPv6Manager.vue`: IPv6 management
- Views:
  - `Dashboard.vue`: Stats and quick actions
  - `Users.vue`: User list with CRUD
  - `Domains.vue`: Domain management with filters
  - `Settings.vue`: System information
- Services:
  - `api.js`: Complete API client
  - `useMainStore.js`: Pinia state management
  - `router/index.js`: Vue Router navigation

### Integration ✅ - API + Scripts
- Users route calls `UserManager.create_user()` on POST
- Domains route calls `DomainManager.create_domain()` on POST
- Domain updates call `DomainManager.change_php_version()`
- SSL route calls `SSLManager.create_ssl(domain_name)`
- IPv6 route calls `IPv6Manager.assign_ipv6(interface, address)`

## Testing on Linux Server

### Prerequisites
```bash
# On Debian 12/13
sudo apt update
sudo apt install -y git curl

# Clone the repository
cd /opt
git clone <your-repo-url> svqpanel
cd svqpanel

# Run installation
sudo bash install.sh
```

### Start Services
```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl status postgresql

# Start SVQPanel API
sudo systemctl start svqpanel
sudo systemctl status svqpanel

# Frontend (development)
cd frontend
npm install
npm run dev
```

### Test Endpoints
```bash
# Create user
curl -X POST http://localhost:8001/api/users \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "secure123",
    "first_name": "Test",
    "last_name": "User"
  }'

# Verify system user created
getent passwd testuser

# Get users list
curl http://localhost:8001/api/users

# Create domain
curl -X POST http://localhost:8001/api/domains \
  -H "Content-Type: application/json" \
  -d '{
    "domain_name": "example.com",
    "user_id": 1,
    "php_version": "8.2"
  }'

# Verify Nginx vhost created
ls /etc/nginx/sites-enabled/

# Verify directories
ls /home/testuser/public_html/

# Setup SSL (requires domain to be accessible)
curl -X POST http://localhost:8001/api/domains/1/ssl \
  -H "Content-Type: application/json" \
  -d '{
    "domain_name": "example.com",
    "auto_renewal": true
  }'

# Verify certificate
sudo certbot certificates
```

### Test Frontend
```bash
# http://localhost:5173
# Navigate to:
# - Dashboard: View stats
# - Users: Create, edit, delete users
# - Domains: Create domains, change PHP, configure SSL
# - Settings: System information
```

## Key Features

### User Management
- Create system users with directories
- Auto-generate /home/username/public_html
- Password hashing in database
- User activation status

### Domain Management
- Create Nginx virtual hosts
- Automatic PHP-FPM socket configuration
- Support for PHP 7.4, 8.0, 8.1, 8.2, 8.3
- Domain enable/disable

### SSL Certificates
- Let's Encrypt integration via certbot
- Auto-renewal enabled
- 90-day validity
- Easy revocation

### IPv6 Support
- Assign multiple IPv6 addresses per domain
- Network interface configuration
- Clean removal

## Troubleshooting

### API not responding
```bash
# Check logs
sudo journalctl -u svqpanel -f

# Test database connection
psql -U panel_user -h localhost -d svqpanel_db -c "SELECT 1;"
```

### Permission denied errors
```bash
# Ensure running as root or with sudo
sudo -u svqpanel python3 -m api.main

# Or adjust system permissions
sudo usermod -aG www-data svqpanel
```

### Nginx not reloading
```bash
# Test Nginx syntax
sudo nginx -t

# Manual reload
sudo systemctl reload nginx
```

### Certbot issues
```bash
# Check existing certificates
sudo certbot certificates

# Manual renewal
sudo certbot renew --force-renewal
```

## Next Steps

1. Deploy on a Debian 12/13 server
2. Configure DNS records for test domains
3. Run full end-to-end testing
4. Add authentication/login system
5. Set resource limits per user
6. Add domain usage statistics
7. Email notifications for SSL expiry

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   Vue 3 Frontend (Port 5173)            │
│         Dashboard │ Users │ Domains │ Settings          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ HTTP/JSON
                       ↓
┌─────────────────────────────────────────────────────────┐
│              FastAPI Backend (Port 8001)                │
│    users.py │ domains.py │ php.py │ ssl.py │ ipv6.py   │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
    ┌────────┐  ┌──────────┐  ┌─────────┐
    │ System │  │PostgreSQL│  │ Managers│
    │Commands│  │ Database │  │ Scripts │
    └────────┘  └──────────┘  └─────────┘
    adduser     Users       UserManager
    useradd     Domains     DomainManager
    nginx       SSL         SSLManager
    certbot     IPv6        IPv6Manager
    ip                      PHPManager
```

---

**Status**: Fase 1-4 Complete ✅
**Ready for**: Production Testing
**Test Environment**: Debian 12/13 Server or WSL2
