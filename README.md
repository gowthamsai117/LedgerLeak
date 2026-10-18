# LedgerLeak

LedgerLeak is an original fictional FinTech support-portal web application for the Hacktify Round 1 web-exploitation challenge.

## Website features

- Public landing page
- Customer registration and sign-in
- Customer dashboard and support-ticket workflow
- Operations URL-preview tool
- Internal diagnostics endpoint intended for the lab's SSRF investigation stage

## Source layout

```text
app/
├── app.py
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── index.html
    ├── login.html
    ├── dashboard.html
    ├── tickets.html
    ├── ticket.html
    ├── new_ticket.html
    ├── preview.html
    └── error.html
requirements.txt
```

## Run locally on Ubuntu

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app/app.py
```

Open `http://127.0.0.1:5000` and register a test customer account.

## Lab safety

This application intentionally contains a server-side URL-fetching feature for a controlled training lab. Run it only on an isolated assessment VM or network. Do not expose the lab to the public internet.

This repository contains website source only. Target provisioning and the Linux privilege-escalation stage will be handled separately.
