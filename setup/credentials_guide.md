# Credentials სრული სია

## Meta (Instagram + Messenger + WhatsApp)
1. developers.facebook.com → My Apps → Create App
2. Add Instagram Basic Display
3. Add Messenger
4. Add WhatsApp Business
5. Generate Page Access Token

Values for .env:
META_VERIFY_TOKEN = გამოიგონე (ნებისმიერი string)
META_ACCESS_TOKEN = Page Access Token
META_PAGE_ID = Facebook Page ID
WHATSAPP_TOKEN = WhatsApp System User Token
WHATSAPP_PHONE_NUMBER_ID = Phone Number ID

## Google Sheets + Calendar
1. console.cloud.google.com
2. Create Project
3. Enable: Google Sheets API + Google Calendar API
4. Create Service Account
5. Download credentials.json
6. Share Sheet და Calendar with service account email

Values for .env:
GOOGLE_SHEETS_CREDENTIALS_JSON = credentials.json content (one line)
GOOGLE_SHEETS_SPREADSHEET_ID = from Sheet URL
GOOGLE_CALENDAR_CREDENTIALS_JSON = same credentials.json
GOOGLE_CALENDAR_ID = Calendar ID

## Email (Gmail)
1. Gmail → Security → 2FA → App Password
2. Create App Password for Mail

Values for .env:
SMTP_HOST = smtp.gmail.com
SMTP_PORT = 587
SMTP_USER = your@gmail.com
SMTP_PASSWORD = app password (16 chars)
MANAGER_EMAIL = manager@company.com
