# Manga Tracker

A modular Python automation tool for tracking manga series and volumes using a local SQLite database.  
This project demonstrates practical experience in building data pipelines, scraper automation, schema design, and lightweight web interfaces — all foundational skills for AI automation and AI infrastructure engineering.

---

## 🔧 Purpose

This project started as a personal tool and evolved into a demonstration of:

- Python-based automation
- Modular scraper architecture
- Structured data ingestion pipelines
- Local database schema design and migrations
- Lightweight Flask UI development
- Real-world debugging (HTML changes, selectors, bot protection)

The same engineering principles apply directly to AI workflows: reproducible pipelines, modular components, and reliable data handling.

---

## 🧱 Architecture Overview

- **Python + SQLite** for a simple, reliable local datastore  
- **Modular scrapers** (Seven Seas, Barnes & Noble) using `requests` + `BeautifulSoup`  
- **Schema helpers** and migration scripts for evolving the database  
- **Flask UI** for browsing and interacting with the dataset  
- **Separation of concerns** between scraping, data models, and presentation  
- **Selector tests** to validate scraper behavior

This mirrors the structure of AI data prep pipelines: clean modules, predictable transformations, and maintainable workflows.

---

## 📂 Key Components

- `app.py` — Flask interface  
- `models.py` — schema definitions and helpers  
- `db.py` — SQLite utilities  
- `seven_seas/` — modular scraper package  
- `static/` + `templates/` — UI assets  
- `test_*.py` — selector and scraper tests  

The local database (`manga.db`) is intentionally excluded from version control.

---

## ▶️ Running the App (Optional)

This project is primarily a portfolio artifact.  
Running it is optional, but possible:

```bash
python app.py
