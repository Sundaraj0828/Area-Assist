# Area-Assist 🗺️

**Area-Assist** is a specialized location-based service application designed to manage and visualize geographical zones. It provides a robust backend to handle spatial coordinates, allowing users to define service areas, track points of interest, and query proximity data through a streamlined RESTful API.

---

## 🛠️ Tech Stack

* **Backend:** Python with **Flask Framework**
* **Database:** **MongoDB** (Optimized for flexible, coordinate-based data)
* **Authentication:** JWT (JSON Web Tokens) via Flask-JWT-Extended
* **Environment:** `python-dotenv` for secure credential management
* **Frontend:** HTML5, CSS3, and JavaScript

---

## ✨ Key Features

* **Zone Management:** Define, save, and categorize custom geographical areas.
* **Coordinate Tracking:** Store and retrieve precise latitude/longitude points.
* **Search & Filter:** Query MongoDB to find specific service zones or locations.
* **Secure API:** Authenticated endpoints to protect sensitive spatial data.
* **Responsive Mapping:** Structured to integrate easily with mapping libraries like Leaflet.js or Google Maps.

---

## 🚀 Getting Started

### 1. Prerequisites
* Python 3.10+
* MongoDB (Local or Atlas)

### 2. Installation
Clone the repository:
```bash
git clone https://github.com/Sundaraj0828/Area-Assist.git
cd Area-Assist
```

### 3. Environment Setup
Create a `.env` file in the root directory:
```env
MONGO_URI=mongodb://localhost:27017/area_assist_db
JWT_SECRET_KEY=your_secure_secret_key
FLASK_APP=app.py
FLASK_ENV=development
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Run the Application
```bash
flask run
```
The application will be available at `http://127.0.0.1:5000/`.

---

## 📁 Project Structure (Flat)

This project uses a flat structure to keep all logic and configuration easily accessible:

```text
Area-Assist/
├── app.py              # Main Flask application, routes, and logic
├── database.py           # MongoDB schemas and data operations
├── .env                # Environment variables (Hidden)
├── requirements.txt    # Python package dependencies
├── static/             # Frontend assets (CSS, JS, Images)
│   ├── css/
│   ├── js/
│   └── img/
├── templates/          # HTML views (Jinja2 templates)
│   └── index.html      # Main interface
└── README.md           # Project documentation
```

---

## 🔗 API Overview

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **GET** | `/` | Renders the dashboard | No |
| **POST** | `/api/auth/login` | Obtain access token | No |
| **GET** | `/api/areas` | Retrieve all saved zones | Yes |
| **POST** | `/api/areas/add` | Save a new coordinate zone | Yes |

---

## 📄 License
This project is licensed under the MIT License.

---

**Developed with ❤️ by [Sundaraj0828]**
