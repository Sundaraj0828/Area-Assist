from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import requests
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from config import Config
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env file
from dotenv import load_dotenv
import os
from pathlib import Path

# Find .env file in the same directory as app.py
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'area-assist-secret-key'
app.config['MONGO_URI'] = os.environ.get('MONGO_URI') or 'mongodb://localhost:27017/areaassist'
app.config['DEBUG'] = os.environ.get('DEBUG', 'True').lower() == 'true'

# Custom Jinja2 filter to convert 24-hour time to 12-hour with AM/PM
@app.template_filter('time_12h')
def time_12h(time_str):
    """Convert 24-hour time string (HH:MM) to 12-hour format with AM/PM"""
    if not time_str:
        return ''
    try:
        # Parse the time string (expects HH:MM format)
        hour, minute = time_str.split(':')
        hour = int(hour)
        minute = int(minute)
        
        # Convert to 12-hour format
        if hour == 0:
            return f"12:{minute:02d} AM"
        elif hour < 12:
            return f"{hour}:{minute:02d} AM"
        elif hour == 12:
            return f"12:{minute:02d} PM"
        else:
            return f"{hour-12}:{minute:02d} PM"
    except:
        return time_str

# Custom Jinja2 filter to expand day ranges to individual days
@app.template_filter('expand_timings')
def expand_timings(timings_str):
    """Expand timing string with day ranges to individual days"""
    if not timings_str:
        return {}
    
    # Define day order
    day_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Initialize all days with None
    result = {day: None for day in day_order}
    
    try:
        # Split by comma to get individual timing entries
        entries = timings_str.split(',')
        
        for entry in entries:
            entry = entry.strip()
            if not entry or ':' not in entry:
                continue
            
            # Split by FIRST colon only to get days and time (time may have colons like 9:00AM)
            parts = entry.split(':', 1)
            days_part = parts[0].strip()
            time_part = parts[1].strip() if len(parts) > 1 else ''
            
            # Determine which days this timing applies to
            selected_days = []
            
            if '-' in days_part:
                # It's a range like Mon-Sun, Mon-Sat, etc.
                range_parts = days_part.split('-')
                if len(range_parts) == 2:
                    start_day = range_parts[0].strip()
                    end_day = range_parts[1].strip()
                    
                    # Find indices
                    if start_day in day_order and end_day in day_order:
                        start_idx = day_order.index(start_day)
                        end_idx = day_order.index(end_day)
                        
                        if end_idx >= start_idx:
                            selected_days = day_order[start_idx:end_idx+1]
                        else:
                            # Handle wrap around (unlikely but just in case)
                            selected_days = day_order[start_idx:] + day_order[:end_idx+1]
            elif days_part in day_order:
                # Single day
                selected_days = [days_part]
            
            # Assign time to selected days
            for day in selected_days:
                if day in result:
                    result[day] = time_part
        
        return result
    except:
        return result

# Categories
CATEGORIES = [
    "Grocery Stores",
    "Fish Market", 
    "Vegetable Shop",
    "Laundry & Dry Cleaning",
    "Water Can Supply",
    "Gas Agency/LPG",
    "Xerox/Stationery",
    "Pharmacy/Medical Store",
    "Mobile Recharge/Repair",
    "Electrician",
    "Plumber",
    "Salon/Beauty Parlour",
    "Auto/Taxi Service"
]

# Initialize MongoDB
def init_db():
    from pymongo import MongoClient
    client = MongoClient(app.config['MONGO_URI'])
    db = client.get_database()
    
    # Create indexes
    db.services.create_index([("location", "2dsphere")])
    db.services.create_index("category")
    db.services.create_index("pincode")
    db.users.create_index("email", unique=True)
    return db

db = None

def get_db():
    global db
    if db is None:
        db = init_db()
    return db

def geocode_address(address, area_name='', pincode=''):
    """
    Convert address to latitude and longitude using Nominatim (OpenStreetMap)
    Returns (lat, lng) tuple or (None, None) if geocoding fails
    """
    try:
        # Build the full address string
        parts = []
        if address:
            parts.append(address)
        if area_name:
            parts.append(area_name)
        if pincode:
            parts.append(pincode)
        
        # Add India for better accuracy
        parts.append('India')
        
        if not parts:
            return None, None
        
        full_address = ', '.join(parts)
        
        # Use Nominatim API (OpenStreetMap)
        base_url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': full_address,
            'format': 'json',
            'limit': 1
        }
        headers = {
            'User-Agent': 'AreaAssist2/1.0'
        }
        
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                lat = float(data[0].get('lat', 0))
                lng = float(data[0].get('lon', 0))
                if lat != 0 and lng != 0:
                    return lat, lng
        
        return None, None
    except Exception as e:
        print(f"Geocoding error: {e}")
        return None, None

def calculate_distance(lat1, lng1, lat2, lng2):
    """
    Calculate distance between two points using Haversine formula
    Returns distance in meters
    """
    from math import radians, cos, sin, asin, sqrt
    
    # Convert to radians
    lat1, lng1, lat2, lng2 = map(radians, [float(lat1), float(lng1), float(lat2), float(lng2)])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    c = 2 * asin(sqrt(a))
    
    # Earth radius in meters
    r = 6371000
    
    return c * r

# Context processor to add user data to all templates
@app.context_processor
def inject_user():
    if 'user_id' in session and 'role' in session:
        database = get_db()
        user_id = session['user_id']
        role = session['role']
        
        if role == 'customer':
            user = database.customers.find_one({"_id": ObjectId(user_id)})
        elif role == 'provider':
            user = database.providers.find_one({"_id": ObjectId(user_id)})
        else:
            user = None
        
        return dict(user=user)
    return dict(user=None)

@app.route('/')
def index():
    database = get_db()
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    return render_template('index.html', categories=active_categories if active_categories else CATEGORIES)

@app.route('/search')
def search():
    database = get_db()
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    pincode = request.args.get('pincode', '')
    area_name = request.args.get('area_name', '')
    category = request.args.get('category', '')
    lat = float(request.args.get('lat', 0))
    lng = float(request.args.get('lng', 0))
    # For unauthenticated users, use 1km radius by default
    default_radius = 1 if not session.get('user_id') else 5
    radius = int(request.args.get('radius', default_radius)) * 1000
    booking_only = request.args.get('booking', '')
    added_services = request.args.get('added_services', '')
    
    # If no coordinates provided, try to get from logged-in customer
    if not lat or not lng:
        if session.get('role') == 'customer':
            user_id = session.get('user_id')
            if user_id:
                customer = database.customers.find_one({"_id": ObjectId(user_id)})
                if customer and customer.get('latitude') and customer.get('longitude'):
                    lat = float(customer.get('latitude'))
                    lng = float(customer.get('longitude'))
                    radius = 5 * 1000  # Default 5km for customer's location
    
    services = []
    search_performed = False  # Track if user performed a search
    
    # Build base query
    base_query = {"status": "approved"}
    if category:
        base_query["category"] = category
    if booking_only:
        base_query["booking_available"] = True
    if added_services:
        base_query["owner_id"] = {"$exists": True, "$ne": None}
    
    # Search by area name
    if area_name:
        search_performed = True
        # For unauthenticated users, geocode the area and calculate distances
        if not session.get('user_id'):
            search_lat, search_lng = None, None
            if area_name:
                search_lat, search_lng = geocode_address('', area_name, pincode)
            if search_lat and search_lng:
                lat, lng = search_lat, search_lng
        
        if lat and lng and lat != 0 and lng != 0:
            # Geocode area_name and calculate distances
            query = {"area_name": {"$regex": area_name, "$options": "i"}, "status": "approved"}
            if category:
                query["category"] = category
            if booking_only:
                query["booking_available"] = True
            services = list(database.services.find(query).limit(20))
            for s in services:
                if s.get('lat') and s.get('lng'):
                    s['distance'] = calculate_distance(lat, lng, s['lat'], s['lng'])
                else:
                    s['distance'] = None
        else:
            query = {"area_name": {"$regex": area_name, "$options": "i"}, "status": "approved"}
            if category:
                query["category"] = category
            if booking_only:
                query["booking_available"] = True
            services = list(database.services.find(query).limit(20))
            for s in services:
                s['distance'] = 0
    elif lat and lng:
        search_performed = True
        match_query = {"status": "approved"}
        if category:
            match_query["category"] = category
        if booking_only:
            match_query["booking_available"] = True
        
        # Get services within radius using geoNear
        nearby_services = list(database.services.aggregate([
            {
                "$geoNear": {
                    "near": {"type": "Point", "coordinates": [lng, lat]},
                    "distanceField": "distance",
                    "maxDistance": radius,
                    "spherical": True
                }
            },
            {"$match": match_query},
            {"$limit": 20}
        ]))
        
        # Also get services without location coordinates
        no_location_query = {
            "status": "approved",
            "$or": [
                {"lat": {"$exists": False}},
                {"lat": None},
                {"lat": ""},
                {"lng": {"$exists": False}},
                {"lng": None},
                {"lng": ""}
            ]
        }
        if category:
            no_location_query["category"] = category
        if booking_only:
            no_location_query["booking_available"] = True
        
        no_location_services = list(database.services.find(no_location_query).limit(20))
        for s in no_location_services:
            s['distance'] = None  # Can't calculate distance without coordinates
        
        # Combine both lists
        services = nearby_services + no_location_services
    elif pincode:
        search_performed = True
        # For unauthenticated users, geocode the pincode and calculate distances
        if not session.get('user_id'):
            search_lat, search_lng = None, None
            if pincode:
                search_lat, search_lng = geocode_address('', '', pincode)
            if search_lat and search_lng:
                lat, lng = search_lat, search_lng
        
        if lat and lng and lat != 0 and lng != 0:
            query = {"pincode": pincode, "status": "approved"}
            if category:
                query["category"] = category
            if booking_only:
                query["booking_available"] = True
            services = list(database.services.find(query).limit(20))
            for s in services:
                if s.get('lat') and s.get('lng'):
                    s['distance'] = calculate_distance(lat, lng, s['lat'], s['lng'])
                else:
                    s['distance'] = None
        else:
            query = {"pincode": pincode, "status": "approved"}
            if category:
                query["category"] = category
            if booking_only:
                query["booking_available"] = True
            services = list(database.services.find(query).limit(20))
            for s in services:
                s['distance'] = 0
    elif category:
        # If category is selected but no location, show services by category
        search_performed = True
        query = {"category": category, "status": "approved"}
        if booking_only:
            query["booking_available"] = True
        services = list(database.services.find(query).limit(20))
        for s in services:
            s['distance'] = 0
    elif booking_only:
        # If only booking filter is set, show services with online booking
        search_performed = True
        services = list(database.services.find({"status": "approved", "booking_available": True}).limit(20))
        for s in services:
            s['distance'] = 0
    else:
        # No search parameters - show recent approved services as default
        services = list(database.services.find({"status": "approved"}).sort("created_at", -1).limit(20))
        for s in services:
            s['distance'] = 0
    
    # Get user's saved services if logged in as customer
    user_saved_ids = []
    if session.get('role') == 'customer' and session.get('user_id'):
        customer = database.customers.find_one({"_id": ObjectId(session.get('user_id'))})
        if customer:
            user_saved_ids = customer.get('saved_services', [])
    
    return render_template('search.html', services=services, categories=active_categories if active_categories else CATEGORIES, 
                           search_params={'pincode': pincode, 'area_name': area_name, 'category': category, 'booking': booking_only},
                           search_performed=search_performed, user_saved_ids=user_saved_ids)

@app.route('/service/<service_id>')
def service_detail(service_id):
    database = get_db()
    service = database.services.find_one({"_id": ObjectId(service_id)})
    if service:
        reviews = list(database.reviews.find({"service_id": service_id}).sort("created_at", -1))
        # Enrich reviews with user information
        for review in reviews:
            # Check in customers first, then providers
            user = database.customers.find_one({"_id": ObjectId(review['user_id'])})
            if not user:
                user = database.providers.find_one({"_id": ObjectId(review['user_id'])})
            if user:
                review['user_name'] = user.get('name', 'Unknown')
                review['user_area'] = user.get('area_name', '')
                review['user_avatar'] = user.get('avatar', '')
            else:
                review['user_name'] = 'Unknown'
                review['user_area'] = ''
                review['user_avatar'] = ''
        
        # Get bookings for this service
        bookings = list(database.bookings.find({"service_id": service_id}).sort("created_at", -1))
        # Enrich bookings with customer information
        for booking in bookings:
            customer = database.customers.find_one({"_id": ObjectId(booking['user_id'])})
            if customer:
                booking['customer_name'] = customer.get('name', 'Unknown')
                booking['customer_phone'] = customer.get('phone', '')
            else:
                booking['customer_name'] = 'Unknown'
                booking['customer_phone'] = ''
        
        # Get provider details for signed-in customers
        provider = None
        if session.get('user_id') and session.get('role') == 'customer':
            owner_id = service.get('owner_id')
            if owner_id:
                provider = database.providers.find_one({"_id": ObjectId(owner_id)})
        
        # Try to get/fetch location coordinates if not available
        map_lat = None
        map_lng = None
        
        # First try service's own coordinates
        if service.get('lat') and service.get('lng'):
            try:
                map_lat = float(service.get('lat'))
                map_lng = float(service.get('lng'))
            except:
                pass
        
        # If no service coordinates, try provider's coordinates
        if (map_lat is None or map_lng is None) and provider:
            if provider.get('latitude') and provider.get('longitude'):
                try:
                    map_lat = float(provider.get('latitude'))
                    map_lng = float(provider.get('longitude'))
                except:
                    pass
        
        # If still no coordinates, try to geocode the address
        if map_lat is None or map_lng is None:
            address = service.get('address', '')
            area_name = service.get('area_name', '')
            pincode = service.get('pincode', '')
            if area_name or address:
                map_lat, map_lng = geocode_address(address, area_name, pincode)
        
        return render_template('service_detail.html', service=service, reviews=reviews, bookings=bookings, provider=provider, map_lat=map_lat, map_lng=map_lng)
    return redirect(url_for('index'))

@app.route('/service/<service_id>/upload-image', methods=['POST'])
def upload_service_image(service_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    database = get_db()
    
    # Verify service exists and user owns it
    service = database.services.find_one({"_id": ObjectId(service_id)})
    if not service:
        return jsonify({'success': False, 'error': 'Service not found'}), 404
    
    # Check if user is the owner or admin
    owner_id = service.get('owner_id')
    if owner_id and str(owner_id) != session.get('user_id') and session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    # Check file type
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return jsonify({'success': False, 'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif, webp'}), 400
    
    try:
        # Create uploads directory if it doesn't exist
        import os
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'services')
        os.makedirs(upload_dir, exist_ok=True)
        
        # Generate unique filename
        from werkzeug.utils import secure_filename
        import uuid
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(upload_dir, filename)
        
        # Save file
        file.save(filepath)
        
        # Update service with image URL
        image_url = url_for('static', filename=f'uploads/services/{filename}')
        
        # If this is the first image, set it as main image, otherwise add to photos array
        if not service.get('image'):
            database.services.update_one(
                {"_id": ObjectId(service_id)},
                {"$set": {"image": image_url}}
            )
        else:
            # Add to photos array
            photos = service.get('photos', [])
            photos.append(image_url)
            database.services.update_one(
                {"_id": ObjectId(service_id)},
                {"$set": {"photos": photos}}
            )
        
        # Check if this is a form submission (not AJAX)
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash('Image uploaded successfully!', 'success')
            return redirect(url_for('service_detail', service_id=service_id))
        
        return jsonify({'success': True, 'image_url': image_url})
    except Exception as e:
        error_msg = str(e)
        # Check if this is a form submission (not AJAX)
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash(f'Upload failed: {error_msg}', 'error')
            return redirect(url_for('service_detail', service_id=service_id))
        return jsonify({'success': False, 'error': error_msg}), 500

@app.route('/service/<service_id>/delete-image', methods=['POST'])
def delete_service_image(service_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    database = get_db()
    
    # Verify service exists and user owns it
    service = database.services.find_one({"_id": ObjectId(service_id)})
    if not service:
        return jsonify({'success': False, 'error': 'Service not found'}), 404
    
    # Check if user is the owner or admin
    if str(service.get('owner_id')) != session.get('user_id') and session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    image_url = request.form.get('image_url')
    if not image_url:
        return jsonify({'success': False, 'error': 'No image URL provided'}), 400
    
    try:
        # Extract filename from URL
        import os
        filename = image_url.split('/')[-1]
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'services', filename)
        
        # Delete file if exists
        if os.path.exists(filepath):
            os.remove(filepath)
        
        # Update database - remove from photos array or clear main image
        if service.get('image') == image_url:
            # If deleting main image, set to first photo or null
            photos = service.get('photos', [])
            new_image = photos[0] if photos else None
            new_photos = photos[1:] if photos else []
            database.services.update_one(
                {"_id": ObjectId(service_id)},
                {"$set": {"image": new_image, "photos": new_photos}}
            )
        elif image_url in service.get('photos', []):
            # Remove from photos array
            photos = service.get('photos', [])
            photos.remove(image_url)
            database.services.update_one(
                {"_id": ObjectId(service_id)},
                {"$set": {"photos": photos}}
            )
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    database = get_db()
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Check if admin already exists
    admin_exists = database.users.find_one({"role": "admin"}) is not None
    
    if request.method == 'POST':
        role = request.form['role']
        
        # Check if admin already exists
        if role == 'admin' and admin_exists:
            flash('An admin account already exists. Cannot create another admin.', 'error')
            return render_template('register.html', categories=active_categories if active_categories else CATEGORIES, admin_exists=admin_exists)
        
        # Providers need admin approval (inactive by default)
        is_active = True if role != 'provider' else False
        
        user_data = {
            "first_name": request.form['first_name'],
            "last_name": request.form['last_name'],
            "name": request.form['first_name'] + " " + request.form['last_name'],
            "email": request.form['email'],
            "phone": request.form['phone'],
            "address": request.form.get('address', ''),
            "area_name": request.form.get('area_name', ''),
            "pincode": request.form.get('pincode', ''),
            "password": generate_password_hash(request.form['password']),
            "role": role,
            "is_active": is_active,
            "created_at": datetime.utcnow(),
            "saved_services": []  # For customers to save favorite services
        }
        
        # For customers, try to geocode the address to get lat/lng
        if role == 'customer':
            address = request.form.get('address', '')
            area_name = request.form.get('area_name', '')
            pincode = request.form.get('pincode', '')
            
            if area_name:
                lat, lng = geocode_address(address, area_name, pincode)
                if lat and lng:
                    user_data['latitude'] = lat
                    user_data['longitude'] = lng
        
        try:
            # Save to separate collections based on role
            if role == 'provider':
                database.providers.insert_one(user_data)
            elif role == 'customer':
                database.customers.insert_one(user_data)
            else:
                # Admin still goes to users collection
                database.users.insert_one(user_data)
            
            if role == 'provider':
                flash('Registration successful! Your account is pending approval from admin.', 'success')
            else:
                flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except:
            flash('Email already registered!', 'error')
    return render_template('register.html', categories=active_categories if active_categories else CATEGORIES, admin_exists=admin_exists)

@app.route('/login', methods=['GET', 'POST'])
def login():
    database = get_db()
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user_type = request.form.get('user_type', '')
        
        user = None
        
        # Check based on selected user type
        if user_type == 'admin':
            user = database.users.find_one({"email": email})
        elif user_type == 'provider':
            user = database.providers.find_one({"email": email})
        elif user_type == 'customer':
            user = database.customers.find_one({"email": email})
        else:
            # Fallback: check all collections if no user type selected
            user = database.users.find_one({"email": email})
            if not user:
                user = database.providers.find_one({"email": email})
            if not user:
                user = database.customers.find_one({"email": email})
        
        if user and check_password_hash(user['password'], password):
            # Verify that the user_type matches the user's role
            if user_type and user.get('role') != user_type:
                flash(f'Invalid credentials for {user_type}!', 'error')
            else:
                session['user_id'] = str(user['_id'])
                session['role'] = user['role']
                session['name'] = user['name']
                
                # Show warning if account is inactive
                if not user.get('is_active', True):
                    flash('Your account is inactive. Some features may be limited.', 'warning')
                else:
                    flash('Login successful!', 'success')
                
                if user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                elif user['role'] == 'provider':
                    return redirect(url_for('provider_dashboard'))
                elif user['role'] == 'customer':
                    return redirect(url_for('customer_dashboard'))
                else:
                    return redirect(url_for('index'))
        else:
            flash('Invalid credentials!', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/provider/register-service', methods=['GET', 'POST'])
def register_service():
    if session.get('role') != 'provider':
        flash('Please login as provider!', 'error')
        return redirect(url_for('login'))
    
    database = get_db()
    user_id = session['user_id']
    
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Get provider's existing services
    existing_services = list(database.services.find({"owner_id": user_id}))
    
    # Get current user data for pre-filling form - from providers collection
    user = database.providers.find_one({"_id": ObjectId(user_id)})
    
    # Get user's location if available
    user_lat = user.get('latitude', 20.5937) if user else 20.5937
    user_lng = user.get('longitude', 78.9629) if user else 78.9629
    
    # Build user's address for map geocoding
    user_address = ''
    if user:
        addr_parts = []
        if user.get('address'): addr_parts.append(user['address'])
        if user.get('area_name'): addr_parts.append(user['area_name'])
        if user.get('pincode'): addr_parts.append(user['pincode'])
        user_address = ', '.join(addr_parts)
    
    if request.method == 'POST':
        # Process timing fields - combine days and time ranges
        timing_days_list = request.form.getlist('timing_days')
        timing_start_list = request.form.getlist('timing_start')
        timing_end_list = request.form.getlist('timing_end')
        
        # Build timings string from multiple rows
        timings_parts = []
        for i in range(len(timing_days_list)):
            days = timing_days_list[i] if i < len(timing_days_list) else 'Mon-Sun'
            start_time = timing_start_list[i] if i < len(timing_start_list) else '09:00'
            end_time = timing_end_list[i] if i < len(timing_end_list) else '18:00'
            # Convert 24h time to 12h format
            try:
                start_hour = int(start_time.split(':')[0])
                start_min = start_time.split(':')[1]
                end_hour = int(end_time.split(':')[0])
                end_min = end_time.split(':')[1]
                
                start_ampm = 'AM' if start_hour < 12 else 'PM'
                if start_hour > 12:
                    start_hour -= 12
                elif start_hour == 0:
                    start_hour = 12
                    
                end_ampm = 'AM' if end_hour < 12 else 'PM'
                if end_hour > 12:
                    end_hour -= 12
                elif end_hour == 0:
                    end_hour = 12
                    
                start_formatted = f"{start_hour}:{start_min}{start_ampm}"
                end_formatted = f"{end_hour}:{end_min}{end_ampm}"
            except:
                start_formatted = start_time
                end_formatted = end_time
            
            timings_parts.append(f"{days}: {start_formatted}-{end_formatted}")
        
        timings_string = ', '.join(timings_parts)
        
        # Get lat/lng from form or try to geocode the address
        lat = request.form.get('lat', '')
        lng = request.form.get('lng', '')
        
        # If no coordinates provided, try to geocode the address
        if not lat or not lng:
            address = request.form.get('address', '')
            area_name = request.form.get('area_name', '')
            pincode = request.form.get('pincode', '')
            if area_name:
                lat, lng = geocode_address(address, area_name, pincode)
        
        service_data = {
            "name": request.form['name'],
            "owner_id": session['user_id'],
            "category": request.form['category'],
            "description": request.form['description'],
            "address": request.form['address'],
            "area_name": request.form.get('area_name', ''),
            "pincode": request.form['pincode'],
            "phone": request.form['phone'],
            "whatsapp": request.form.get('whatsapp', ''),
            "timings": timings_string,
            "lat": lat,
            "lng": lng,
            "location": {
                "type": "Point",
                "coordinates": [
                    float(lng) if lng else 0,
                    float(lat) if lat else 0
                ]
            },
            "services": request.form.getlist('services'),
            "booking_available": request.form.get('booking_available') == 'true',
            "photos": [],
            "status": "pending",
            "created_at": datetime.utcnow()
        }
        database.services.insert_one(service_data)
        flash('Service registered successfully! Awaiting approval.', 'success')
        return redirect(url_for('provider_dashboard'))
    return render_template('register_service.html', categories=active_categories, existing_services=existing_services, user=user, user_lat=user_lat, user_lng=user_lng, user_address=user_address)

@app.route('/provider/edit_service/<service_id>', methods=['GET', 'POST'])
def edit_service(service_id):
    if session.get('role') != 'provider':
        flash('Please login as provider!', 'error')
        return redirect(url_for('login'))
    
    database = get_db()
    user_id = session['user_id']
    
    # Get the service to edit
    service = database.services.find_one({"_id": ObjectId(service_id), "owner_id": user_id})
    if not service:
        flash('Service not found!', 'error')
        return redirect(url_for('provider_dashboard'))
    
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Get current user data
    user = database.providers.find_one({"_id": ObjectId(user_id)})
    
    # Get service's location
    service_lat = service.get('lat', '')
    service_lng = service.get('lng', '')
    
    if request.method == 'POST':
        # Process timing fields
        timing_days_list = request.form.getlist('timing_days')
        timing_start_list = request.form.getlist('timing_start')
        timing_end_list = request.form.getlist('timing_end')
        
        timings_parts = []
        for i in range(len(timing_days_list)):
            days = timing_days_list[i] if i < len(timing_days_list) else 'Mon-Sun'
            start_time = timing_start_list[i] if i < len(timing_start_list) else '09:00'
            end_time = timing_end_list[i] if i < len(timing_end_list) else '18:00'
            
            try:
                start_hour = int(start_time.split(':')[0])
                start_min = start_time.split(':')[1]
                end_hour = int(end_time.split(':')[0])
                end_min = end_time.split(':')[1]
                
                start_ampm = 'AM' if start_hour < 12 else 'PM'
                if start_hour > 12:
                    start_hour -= 12
                elif start_hour == 0:
                    start_hour = 12
                    
                end_ampm = 'AM' if end_hour < 12 else 'PM'
                if end_hour > 12:
                    end_hour -= 12
                elif end_hour == 0:
                    end_hour = 12
                    
                start_formatted = f"{start_hour}:{start_min}{start_ampm}"
                end_formatted = f"{end_hour}:{end_min}{end_ampm}"
            except:
                start_formatted = start_time
                end_formatted = end_time
            
            timings_parts.append(f"{days}: {start_formatted}-{end_formatted}")
        
        timings_string = ', '.join(timings_parts)
        
        # Get lat/lng from form
        lat = request.form.get('lat', '')
        lng = request.form.get('lng', '')
        
        # Update service
        updated_data = {
            "name": request.form['name'],
            "category": request.form['category'],
            "description": request.form['description'],
            "address": request.form['address'],
            "area_name": request.form.get('area_name', ''),
            "pincode": request.form['pincode'],
            "phone": request.form['phone'],
            "whatsapp": request.form.get('whatsapp', ''),
            "timings": timings_string,
            "lat": lat,
            "lng": lng,
            "location": {
                "type": "Point",
                "coordinates": [
                    float(lng) if lng else 0,
                    float(lat) if lat else 0
                ]
            },
            "services": request.form.getlist('services'),
            "booking_available": request.form.get('booking_available') == 'true'
        }
        
        database.services.update_one({"_id": ObjectId(service_id)}, {"$set": updated_data})
        
        # If service was approved, keep it approved, otherwise keep pending
        # (don't change status on edit)
        
        flash('Service updated successfully!', 'success')
        return redirect(url_for('provider_dashboard'))
    
    return render_template('register_service.html', categories=active_categories, existing_services=[], user=user, service=service, user_lat=service_lat or user.get('latitude', 20.5937), user_lng=service_lng or user.get('longitude', 78.9629), user_address='')

@app.route('/customer/dashboard')
def customer_dashboard():
    if session.get('role') != 'customer':
        return redirect(url_for('login'))
    
    database = get_db()
    user_id = session['user_id']
    
    # Get user info - from customers collection
    user = database.customers.find_one({"_id": ObjectId(user_id)})
    
    # Get user's location for nearby services
    user_lat = None
    user_lng = None
    
    # First check if user has stored coordinates
    if user.get('latitude') and user.get('longitude'):
        user_lat = float(user.get('latitude'))
        user_lng = float(user.get('longitude'))
    else:
        # Try to geocode the user's address
        address = user.get('address', '') if user else ''
        area_name = user.get('area_name', '') if user else ''
        pincode = user.get('pincode', '') if user else ''
        
        if area_name:
            user_lat, user_lng = geocode_address(address, area_name, pincode)
            
            # Optionally save the coordinates for future use
            if user_lat and user_lng:
                database.customers.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {"latitude": user_lat, "longitude": user_lng}}
                )
        print(user_lat, user_lng)
    
    # Search for nearby services (2km range = 2000 meters)
    nearby_services = []
    if user_lat and user_lng:
        radius = 2 * 1000  # 2km in meters
        nearby_services = list(database.services.aggregate([
            {
                "$geoNear": {
                    "near": {"type": "Point", "coordinates": [user_lng, user_lat]},
                    "distanceField": "distance",
                    "maxDistance": radius,
                    "spherical": True
                }
            },
            {"$match": {"status": "approved"}},
            {"$limit": 20}
        ]))
    
    # If no nearby services found via geo, try searching by area_name
    if not nearby_services and user and user.get('area_name'):
        area_name = user.get('area_name', '')
        nearby_services = list(database.services.find({
            "status": "approved",
            "area_name": {"$regex": area_name, "$options": "i"}
        }).limit(20))
        # Add dummy distance for display
        for service in nearby_services:
            service['distance'] = None
    
    # Get bookings made by customer
    bookings = list(database.bookings.find({"user_id": user_id}).sort("created_at", -1))
    
    # Get service and provider names for each booking
    for booking in bookings:
        service_id = booking.get('service_id')
        if service_id:
            try:
                service = database.services.find_one({"_id": ObjectId(service_id)})
            except:
                service = None
            if service:
                booking['service_name'] = service.get('name', 'Unknown')
                owner_id = service.get('owner_id')
                if owner_id:
                    try:
                        provider = database.providers.find_one({"_id": ObjectId(owner_id)})
                    except:
                        provider = None
                    if provider:
                        booking['provider_name'] = provider.get('first_name', '') + ' ' + provider.get('last_name', '')
                    else:
                        booking['provider_name'] = ''
                else:
                    booking['provider_name'] = ''
        else:
            booking['service_name'] = 'Unknown'
            booking['provider_name'] = ''
    
    # Get reviews given by customer
    reviews_given = list(database.reviews.find({"user_id": user_id}).sort("created_at", -1))
    
    # For each review, get service name
    for review in reviews_given:
        service = database.services.find_one({"_id": review.get('service_id')})
        if service:
            review['service_name'] = service.get('name', 'Unknown Service')
    
    # Get saved/favorited services from user's saved_services list
    saved_services = []
    user_saved_ids = user.get('saved_services', []) if user else []
    for service_id in user_saved_ids:
        service = database.services.find_one({"_id": ObjectId(service_id), "status": "approved"})
        if service:
            saved_services.append(service)
    
    # Get active categories
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Get services with booking available within 2km
    booking_services = []
    if user_lat and user_lng:
        radius = 2 * 1000  # 2km in meters
        booking_services = list(database.services.aggregate([
            {
                "$geoNear": {
                    "near": {"type": "Point", "coordinates": [user_lng, user_lat]},
                    "distanceField": "distance",
                    "maxDistance": radius,
                    "spherical": True
                }
            },
            {"$match": {"status": "approved", "booking_available": True}},
            {"$limit": 10}
        ]))
    else:
        booking_services = list(database.services.find({
            "status": "approved",
            "booking_available": True
        }).limit(10))
    
    return render_template('customer_dashboard.html', user=user, bookings=bookings, 
                          reviews_given=reviews_given, saved_services=saved_services,
                          categories=active_categories if active_categories else CATEGORIES,
                          booking_services=booking_services, nearby_services=nearby_services,
                          user_saved_ids=user_saved_ids)

@app.route('/provider/dashboard')
def provider_dashboard():
    if session.get('role') != 'provider':
        return redirect(url_for('login'))
    
    database = get_db()
    user_id = session['user_id']
    
    # Get user to check if active - from providers collection
    user = database.providers.find_one({"_id": ObjectId(user_id)})
    is_active = user.get('is_active', True) if user else True
    
    services = list(database.services.find({"owner_id": user_id}))
    total_views = sum(s.get('views', 0) for s in services)
    total_calls = sum(s.get('calls', 0) for s in services)
    # Get bookings for this provider's services
    # First get provider's services to find bookings
    provider_services = list(database.services.find({"owner_id": user_id}))
    service_ids = [s['_id'] for s in provider_services]
    
    # Query bookings by service IDs (more reliable)
    if service_ids:
        # Convert all service_ids to strings for matching
        service_id_strings = []
        for sid in service_ids:
            if isinstance(sid, ObjectId):
                service_id_strings.append(str(sid))
            else:
                service_id_strings.append(sid)
        bookings = list(database.bookings.find({"service_id": {"$in": service_id_strings}}).sort("created_at", -1))
    else:
        bookings = []
    
    # Get service and customer names for each booking
    for booking in bookings:
        service_id = booking.get('service_id')
        if service_id:
            try:
                service = database.services.find_one({"_id": ObjectId(service_id)})
            except:
                service = None
            if service:
                booking['service_name'] = service.get('name', 'Unknown')
        else:
            booking['service_name'] = 'Unknown'
        
        # Get customer name
        customer_id = booking.get('user_id')
        if customer_id:
            try:
                customer = database.customers.find_one({"_id": ObjectId(customer_id)})
            except:
                customer = None
            if customer:
                booking['customer_name'] = customer.get('first_name', '') + ' ' + customer.get('last_name', '')
                booking['customer_phone'] = customer.get('phone', 'N/A')
                booking['customer_email'] = customer.get('email', 'N/A')
            else:
                booking['customer_name'] = 'Unknown'
                booking['customer_phone'] = 'N/A'
                booking['customer_email'] = 'N/A'
        else:
            booking['customer_name'] = 'Unknown'
            booking['customer_phone'] = 'N/A'
            booking['customer_email'] = 'N/A'
    
    # Count happy customers based on positive ratings (4+ stars)
    service_ids = [s['_id'] for s in services]
    if service_ids:
        happy_customers = database.reviews.count_documents({
            "service_id": {"$in": service_ids},
            "rating": {"$gte": 4}
        })
    else:
        happy_customers = 0
    
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    return render_template('provider_dashboard.html', services=services,
                          total_views=total_views, total_calls=total_calls, 
                          bookings=bookings, categories=active_categories if active_categories else CATEGORIES,
                          is_active=is_active, happy_customers=happy_customers, user=user)

@app.route('/provider/services/catalogue')
def services_catalogue():
    if session.get('role') != 'provider':
        return redirect(url_for('login'))
    
    database = get_db()
    user_id = session['user_id']
    
    services = list(database.services.find({"owner_id": user_id}))
    
    # Calculate avg_rating for each service if not present
    for service in services:
        if 'avg_rating' not in service:
            ratings = list(database.reviews.find({"service_id": str(service['_id'])}))
            if ratings:
                avg = sum(r['rating'] for r in ratings) / len(ratings)
                service['avg_rating'] = round(avg, 1)
            else:
                service['avg_rating'] = None
    
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Get category objects for dropdown
    categories = list(database.categories.find({"is_active": True}))
    
    return render_template('services_catalogue.html', services=services,
                          categories=categories if categories else [])

@app.route('/provider/toggle_service/<service_id>', methods=['POST'])
def toggle_service_status(service_id):
    if session.get('role') != 'provider':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    database = get_db()
    user_id = session['user_id']
    
    # Verify the service belongs to this provider
    service = database.services.find_one({"_id": ObjectId(service_id), "owner_id": user_id})
    if not service:
        return jsonify({'success': False, 'error': 'Service not found'}), 404
    
    # Toggle the status between active/inactive for approved services
    current_status = service.get('status', 'approved')
    new_status = 'inactive' if current_status == 'approved' else 'approved'
    
    database.services.update_one(
        {"_id": ObjectId(service_id)},
        {"$set": {"status": new_status}}
    )
    
    return jsonify({'success': True, 'new_status': new_status})

@app.route('/provider/clone_service/<service_id>', methods=['POST'])
def clone_service(service_id):
    if session.get('role') != 'provider':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        return redirect(url_for('login'))
    
    database = get_db()
    user_id = session['user_id']
    
    # Get the original service
    original_service = database.services.find_one({"_id": ObjectId(service_id)})
    if not original_service:
        flash('Service not found!', 'error')
        return redirect(url_for('provider_dashboard'))
    
    # Create a clone with new data
    cloned_data = {
        "name": original_service.get('name', '') + ' - Branch',
        "owner_id": user_id,
        "category": original_service.get('category', ''),
        "description": original_service.get('description', ''),
        "address": original_service.get('address', ''),
        "area_name": original_service.get('area_name', ''),
        "pincode": original_service.get('pincode', ''),
        "phone": original_service.get('phone', ''),
        "whatsapp": original_service.get('whatsapp', ''),
        "timings": original_service.get('timings', ''),
        "lat": original_service.get('lat', ''),
        "lng": original_service.get('lng', ''),
        "location": original_service.get('location', {"type": "Point", "coordinates": [0, 0]}),
        "services": original_service.get('services', []),
        "booking_available": original_service.get('booking_available', False),
        "photos": [],
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    
    database.services.insert_one(cloned_data)
    flash('Service cloned successfully! The cloned service is pending approval.', 'success')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Service cloned successfully!'})
    
    return redirect(url_for('provider_dashboard'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Get stats for last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    stats = {
        "total_services": database.services.count_documents({}),
        "verified_providers": database.providers.count_documents({}),
        "active_users": database.customers.count_documents({}),
        "pending_approvals": database.services.count_documents({"status": "pending"}),
        "total_bookings": database.bookings.count_documents({}),
        "total_reviews": database.reviews.count_documents({}),
        "approved_services": database.services.count_documents({"status": "approved"}),
        "rejected_services": database.services.count_documents({"status": "rejected"}),
        "new_users_30d": database.providers.count_documents({"created_at": {"$gte": thirty_days_ago}}) + database.customers.count_documents({"created_at": {"$gte": thirty_days_ago}}),
        "new_services_30d": database.services.count_documents({"created_at": {"$gte": thirty_days_ago}})
    }
    
    pending_services = list(database.services.find({"status": "pending"}))
    recent_services = list(database.services.find().sort("created_at", -1).limit(5))
    recent_bookings = list(database.bookings.find().sort("created_at", -1).limit(5))
    
    return render_template('admin_dashboard.html', stats=stats, pending_services=pending_services,
                          recent_services=recent_services, recent_bookings=recent_bookings, categories=active_categories if active_categories else CATEGORIES)

@app.route('/admin/provider/<provider_id>/services')
def admin_provider_services(provider_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    provider = database.providers.find_one({"_id": ObjectId(provider_id)})
    
    if not provider:
        flash('Provider not found!', 'error')
        return redirect(url_for('admin_dashboard'))
    
    services = list(database.services.find({"owner_id": provider_id}))
    
    return render_template('admin_provider_services.html', provider=provider, services=services)

@app.route('/admin/providers')
def admin_providers():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    
    # Get all providers with their service counts
    providers = list(database.providers.find())
    
    # Add service count and service names to each provider
    for provider in providers:
        provider['service_count'] = database.services.count_documents({"owner_id": str(provider['_id'])})
        # Get service names for this provider
        provider_services = list(database.services.find({"owner_id": str(provider['_id'])}, {"name": 1}))
        provider['service_names'] = [s['name'] for s in provider_services]
    
    return render_template('admin_providers.html', providers=providers)

@app.route('/admin/approve/<service_id>')
def approve_service(service_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    database.services.update_one({"_id": ObjectId(service_id)}, {"$set": {"status": "approved"}})
    flash('Service approved!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject/<service_id>')
def reject_service(service_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    database.services.update_one({"_id": ObjectId(service_id)}, {"$set": {"status": "rejected"}})
    flash('Service rejected!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
def admin_users():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Get counts
    provider_count = database.providers.count_documents({})
    customer_count = database.customers.count_documents({})
    
    # Get unique areas for providers
    provider_areas = database.providers.distinct("area_name", {"area_name": {"$ne": None, "$ne": ""}})
    
    per_page = 5
    
    # Get filter parameters
    provider_area = request.args.get('provider_area', '')
    provider_status = request.args.get('provider_status', '')
    has_services_filter = request.args.get('has_services', '')
    
    # Get provider page from query params
    provider_page = int(request.args.get('provider_page', 1))
    
    # Build provider query with filters
    provider_query = {}
    if provider_area:
        provider_query["area_name"] = provider_area
    if provider_status:
        if provider_status == 'active':
            provider_query["is_active"] = True
        elif provider_status == 'inactive':
            provider_query["is_active"] = False
    
    # Get filtered provider count
    filtered_provider_count = database.providers.count_documents(provider_query)
    provider_total_pages = max(1, (filtered_provider_count + per_page - 1) // per_page)
    if provider_page < 1: provider_page = 1
    if provider_page > provider_total_pages: provider_page = provider_total_pages
    
    # Get customer page from query params
    customer_page = int(request.args.get('customer_page', 1))
    customer_total_pages = max(1, (customer_count + per_page - 1) // per_page)
    if customer_page < 1: customer_page = 1
    if customer_page > customer_total_pages: customer_page = customer_total_pages
    
    # Get services for each provider (get ALL providers first to build complete map)
    all_providers = list(database.providers.find(provider_query).sort("created_at", -1))
    
    provider_services = {}
    for provider in all_providers:
        services = list(database.services.find({"owner_id": str(provider['_id'])}))
        provider_services[str(provider['_id'])] = services
    
    # Filter ALL providers based on has_services BEFORE pagination
    if has_services_filter:
        filtered_providers = []
        for provider in all_providers:
            services = provider_services.get(str(provider['_id']), [])
            if has_services_filter == 'yes' and len(services) > 0:
                filtered_providers.append(provider)
            elif has_services_filter == 'no' and len(services) == 0:
                filtered_providers.append(provider)
        all_providers = filtered_providers
    
    # Recalculate pagination based on filtered results
    filtered_provider_count = len(all_providers)
    provider_total_pages = max(1, (filtered_provider_count + per_page - 1) // per_page)
    if provider_page < 1: provider_page = 1
    if provider_page > provider_total_pages: provider_page = provider_total_pages
    
    # Apply pagination to filtered providers
    providers = all_providers[(provider_page - 1) * per_page:provider_page * per_page]
    
    # Get customers with pagination (sorted by created_at in reverse - newest first)
    customers = list(database.customers.find({}).sort("created_at", -1).skip((customer_page - 1) * per_page).limit(per_page))
    
    return render_template('admin_users.html', 
                          categories=active_categories if active_categories else CATEGORIES, 
                          providers=providers, customers=customers,
                          provider_services=provider_services,
                          provider_count=provider_count, customer_count=customer_count,
                          provider_page=provider_page, provider_total_pages=provider_total_pages,
                          customer_page=customer_page, customer_total_pages=customer_total_pages,
                          provider_area=provider_area, provider_status=provider_status,
                          provider_areas=provider_areas, has_services=has_services_filter)

@app.route('/admin/user/<user_id>/toggle-active')
def toggle_user_active(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    
    # Check in providers first, then customers
    user = database.providers.find_one({"_id": ObjectId(user_id)})
    if not user:
        user = database.customers.find_one({"_id": ObjectId(user_id)})
    
    if user:
        new_status = not user.get('is_active', True)
        role = user.get('role', 'provider')
        
        # If trying to activate a provider, check if they have at least one service
        if role == 'provider' and new_status:
            service_count = database.services.count_documents({"owner_id": user_id})
            if service_count == 0:
                flash('Cannot activate provider - they must have at least one service!', 'danger')
                return redirect(url_for('admin_users'))
        
        # Update in the appropriate collection
        if role == 'provider':
            database.providers.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_active": new_status}})
            
            # If activating provider, automatically approve all their services
            if new_status:
                database.services.update_many(
                    {"owner_id": user_id, "status": "pending"},
                    {"$set": {"status": "approved"}}
                )
                approved_count = database.services.count_documents({"owner_id": user_id, "status": "approved"})
                if approved_count > 0:
                    flash(f'User activated! {approved_count} service(s) also approved.', 'success')
                else:
                    flash('User activated!', 'success')
            else:
                flash('User deactivated!', 'success')
        else:
            database.customers.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_active": new_status}})
            status_text = "activated" if new_status else "deactivated"
            flash(f'User {status_text}!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/api/provider/<provider_id>/services')
def admin_api_provider_services(provider_id):
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    database = get_db()
    services = list(database.services.find({"owner_id": provider_id}))
    
    # Convert ObjectId to string for JSON serialization
    for service in services:
        service['_id'] = str(service['_id'])
        service['owner_id'] = str(service.get('owner_id', ''))
    
    return jsonify({'services': services})

@app.route('/admin/user/<user_id>/delete')
def delete_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    
    # First check if user exists in any collection
    user = database.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        user = database.providers.find_one({"_id": ObjectId(user_id)})
    if not user:
        user = database.customers.find_one({"_id": ObjectId(user_id)})
    
    if user:
        role = user.get('role', '')
        # Delete from appropriate collection
        if role == 'admin':
            database.users.delete_one({"_id": ObjectId(user_id)})
        elif role == 'provider':
            database.providers.delete_one({"_id": ObjectId(user_id)})
        else:
            database.customers.delete_one({"_id": ObjectId(user_id)})
    
    # Delete user's services and related data
    database.services.delete_many({"owner_id": user_id})
    database.bookings.delete_many({"user_id": user_id})
    database.bookings.delete_many({"provider_id": user_id})
    database.reviews.delete_many({"user_id": user_id})
    flash('User and all related data deleted!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/services')
def admin_services():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category', '')
    
    query = {}
    if status_filter:
        query['status'] = status_filter
    if category_filter:
        query['category'] = category_filter
    
    services = list(database.services.find(query).sort("created_at", -1))
    
    return render_template('admin_services.html', services=services, categories=active_categories if active_categories else CATEGORIES,
                          status_filter=status_filter, category_filter=category_filter)

@app.route('/admin/service/<service_id>/delete')
def delete_service(service_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    database.services.delete_one({"_id": ObjectId(service_id)})
    database.bookings.delete_many({"service_id": service_id})
    database.reviews.delete_many({"service_id": service_id})
    flash('Service and all related data deleted!', 'success')
    return redirect(url_for('admin_services'))

@app.route('/admin/reports')
def admin_reports():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    # Get active categories from database
    active_categories = [c['name'] for c in database.categories.find({"is_active": True})]
    
    # Get date ranges
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # User stats
    user_stats = {
        "total": database.providers.count_documents({}) + database.customers.count_documents({}),
        "admins": database.users.count_documents({"role": "admin"}),
        "providers": database.providers.count_documents({}),
        "customers": database.customers.count_documents({}),
        "new_this_week": database.providers.count_documents({"created_at": {"$gte": week_ago}}) + database.customers.count_documents({"created_at": {"$gte": week_ago}}),
        "new_this_month": database.providers.count_documents({"created_at": {"$gte": month_ago}}) + database.customers.count_documents({"created_at": {"$gte": month_ago}})
    }
    
    # Service stats
    service_stats = {
        "total": database.services.count_documents({}),
        "approved": database.services.count_documents({"status": "approved"}),
        "pending": database.services.count_documents({"status": "pending"}),
        "rejected": database.services.count_documents({"status": "rejected"}),
        "new_this_week": database.services.count_documents({"created_at": {"$gte": week_ago}}),
        "new_this_month": database.services.count_documents({"created_at": {"$gte": month_ago}})
    }
    
    # Booking stats
    booking_stats = {
        "total": database.bookings.count_documents({}),
        "pending": database.bookings.count_documents({"status": "pending"}),
        "confirmed": database.bookings.count_documents({"status": "confirmed"}),
        "completed": database.bookings.count_documents({"status": "completed"}),
        "cancelled": database.bookings.count_documents({"status": "cancelled"}),
        "this_week": database.bookings.count_documents({"created_at": {"$gte": week_ago}}),
        "this_month": database.bookings.count_documents({"created_at": {"$gte": month_ago}})
    }
    
    # Category breakdown
    category_stats = list(database.services.aggregate([
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]))
    
    # Top providers by services
    top_providers = list(database.services.aggregate([
        {"$group": {"_id": "$owner_id", "service_count": {"$sum": 1}}},
        {"$sort": {"service_count": -1}},
        {"$limit": 10},
        {"$lookup": {"from": "users", "localField": "_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$project": {"name": "$user.name", "email": "$user.email", "service_count": 1}}
    ]))
    
    return render_template('admin_reports.html', user_stats=user_stats, service_stats=service_stats,
                          booking_stats=booking_stats, category_stats=category_stats,
                          top_providers=top_providers, categories=active_categories if active_categories else CATEGORIES)

@app.route('/admin/categories', methods=['GET', 'POST'])
def admin_categories():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    
    # Initialize default categories if not exists
    if database.categories.count_documents({}) == 0:
        default_categories = [
            {"name": "Grocery Stores", "description": "Local grocery and convenience stores", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Fish Market", "description": "Fresh fish and seafood vendors", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Vegetable Shop", "description": "Fresh fruits and vegetables", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Laundry & Dry Cleaning", "description": "Laundry services and dry cleaning", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Water Can Supply", "description": "Drinking water can delivery", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Gas Agency/LPG", "description": "LPG gas cylinder suppliers", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Xerox/Stationery", "description": "Printing, xerox and stationery shops", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Pharmacy/Medical Store", "description": "Pharmacies and medical supply stores", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Mobile Recharge/Repair", "description": "Mobile phone recharge and repair services", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Electrician", "description": "Electrical repair and installation services", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Plumber", "description": "Plumbing repair and installation services", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Salon/Beauty Parlour", "description": "Salon and beauty services", "is_active": True, "created_at": datetime.utcnow()},
            {"name": "Auto/Taxi Service", "description": "Auto rickshaw and taxi services", "is_active": True, "created_at": datetime.utcnow()}
        ]
        database.categories.insert_many(default_categories)
    
    # Handle POST - add new category
    if request.method == 'POST':
        category_name = request.form.get('name', '').strip()
        category_description = request.form.get('description', '').strip()
        
        if category_name:
            # Check if category already exists
            existing = database.categories.find_one({"name": category_name})
            if existing:
                flash('Category already exists!', 'error')
            else:
                database.categories.insert_one({
                    "name": category_name,
                    "description": category_description,
                    "is_active": True,
                    "created_at": datetime.utcnow()
                })
                flash('Category added successfully!', 'success')
        return redirect(url_for('admin_categories'))
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 8
    skip = (page - 1) * per_page
    
    # Get total count, active count, and paginated categories
    total_count = database.categories.count_documents({})
    active_count = database.categories.count_documents({"is_active": True})
    all_categories = list(database.categories.find().sort("name", 1).skip(skip).limit(per_page))
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template('admin_categories.html', categories=all_categories, CATEGORIES=CATEGORIES, 
                          page=page, total_pages=total_pages, total_count=total_count, active_count=active_count)

@app.route('/admin/category/<category_id>/toggle')
def toggle_category(category_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    category = database.categories.find_one({"_id": ObjectId(category_id)})
    if category:
        new_status = not category.get('is_active', True)
        database.categories.update_one({"_id": ObjectId(category_id)}, {"$set": {"is_active": new_status}})
        status_text = "activated" if new_status else "deactivated"
        flash(f'Category {status_text}!', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/category/<category_id>/delete')
def delete_category(category_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    database = get_db()
    database.categories.delete_one({"_id": ObjectId(category_id)})
    flash('Category deleted!', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/book', methods=['POST'])
def book_service():
    if not session.get('user_id'):
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    database = get_db()
    
    # Check if provider is active
    provider_id = request.form['provider_id']
    provider = database.providers.find_one({"_id": ObjectId(provider_id)})
    
    if not provider or not provider.get('is_active', True):
        flash('This provider is currently inactive. You cannot place a booking.', 'error')
        return redirect(url_for('index'))
    
    booking_data = {
        "service_id": request.form['service_id'],
        "user_id": session['user_id'],
        "provider_id": provider_id,
        "date": request.form['date'],
        "time": request.form['time'],
        "notes": request.form.get('notes', ''),
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    database.bookings.insert_one(booking_data)
    flash('Booking request sent!', 'success')
    return redirect(url_for('customer_dashboard'))

@app.route('/booking/update-status', methods=['POST'])
def update_booking_status():
    if not session.get('user_id'):
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    database = get_db()
    booking_id = request.form.get('booking_id')
    new_status = request.form.get('status')
    
    try:
        database.bookings.update_one(
            {"_id": ObjectId(booking_id)},
            {"$set": {"status": new_status}}
        )
        flash(f'Booking {new_status}!', 'success')
    except Exception as e:
        flash(f'Error updating booking: {str(e)}', 'error')
    
    return redirect(url_for('provider_dashboard'))

@app.route('/add-review', methods=['POST'])
def add_review():
    if not session.get('user_id'):
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    database = get_db()
    review_data = {
        "service_id": request.form['service_id'],
        "user_id": session['user_id'],
        "rating": int(request.form['rating']),
        "comment": request.form['comment'],
        "created_at": datetime.utcnow()
    }
    database.reviews.insert_one(review_data)
    
    ratings = list(database.reviews.find({"service_id": request.form['service_id']}))
    avg_rating = sum(r['rating'] for r in ratings) / len(ratings)
    database.services.update_one({"_id": ObjectId(request.form['service_id'])}, 
                          {"$set": {"avg_rating": round(avg_rating, 1)}})
    
    flash('Review added!', 'success')
    return redirect(url_for('service_detail', service_id=request.form['service_id']))

@app.route('/profile', methods=['GET'])
def profile():
    if not session.get('user_id'):
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    database = get_db()
    
    # Allow admin to view other users
    view_user_id = request.args.get('user_id') or session.get('user_id')
    
    # Only allow admin to view other users
    if request.args.get('user_id') and session.get('role') != 'admin':
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    # Check in users first (for admin), then providers, then customers
    user = database.users.find_one({"_id": ObjectId(view_user_id)})
    if not user:
        user = database.providers.find_one({"_id": ObjectId(view_user_id)})
    if not user:
        user = database.customers.find_one({"_id": ObjectId(view_user_id)})
    
    if not user:
        flash('User not found!', 'error')
        return redirect(url_for('index'))
    
    # Extract first_name and last_name from name if not present (backward compatibility)
    if 'first_name' not in user or 'last_name' not in user:
        full_name = user.get('name', '')
        name_parts = full_name.split(' ', 1) if full_name else ['', '']
        user['first_name'] = name_parts[0]
        user['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
    
    # Get user's services if provider
    services = []
    if user.get('role') == 'provider':
        services = list(database.services.find({"owner_id": view_user_id}))
    
    return render_template('profile.html', user=user, services=services)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if not session.get('user_id'):
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    name = first_name + " " + last_name
    phone = request.form.get('phone')
    address = request.form.get('address')
    pincode = request.form.get('pincode')
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    
    database = get_db()
    user_role = session.get('role')
    
    # Update in the appropriate collection based on role
    if user_role == 'provider':
        database.providers.update_one(
            {"_id": ObjectId(session.get('user_id'))},
            {"$set": {
                "first_name": first_name,
                "last_name": last_name,
                "name": name,
                "phone": phone,
                "address": address,
                "pincode": pincode
            }}
        )
    elif user_role == 'customer':
        # Build update data for customer
        customer_update = {
            "first_name": first_name,
            "last_name": last_name,
            "name": name,
            "phone": phone,
            "address": address,
            "pincode": pincode
        }
        
        # Add latitude and longitude if provided
        if latitude:
            customer_update['latitude'] = latitude
        if longitude:
            customer_update['longitude'] = longitude
        
        database.customers.update_one(
            {"_id": ObjectId(session.get('user_id'))},
            {"$set": customer_update}
        )
    else:
        # Admin
        database.users.update_one(
            {"_id": ObjectId(session.get('user_id'))},
            {"$set": {
                "first_name": first_name,
                "last_name": last_name,
                "name": name,
                "phone": phone,
                "address": address,
                "pincode": pincode
            }}
        )
    
    session['name'] = name
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('profile'))

@app.route('/api/save_coordinates', methods=['POST'])
def save_coordinates():
    """API endpoint to save customer coordinates via AJAX"""
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    if session.get('role') != 'customer':
        return jsonify({'success': False, 'error': 'Only customers can save coordinates'}), 403
    
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    
    if not latitude or not longitude:
        return jsonify({'success': False, 'error': 'Coordinates required'}), 400
    
    try:
        database = get_db()
        database.customers.update_one(
            {"_id": ObjectId(session.get('user_id'))},
            {"$set": {
                "latitude": latitude,
                "longitude": longitude
            }}
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_service_location', methods=['POST'])
def update_service_location():
    """API endpoint to save service location coordinates via AJAX"""
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    if session.get('role') != 'provider':
        return jsonify({'success': False, 'error': 'Only providers can update service location'}), 403
    
    service_id = request.form.get('service_id')
    lat = request.form.get('lat')
    lng = request.form.get('lng')
    
    if not service_id or not lat or not lng:
        return jsonify({'success': False, 'error': 'Service ID and coordinates required'}), 400
    
    try:
        database = get_db()
        # Verify the service belongs to this provider
        service = database.services.find_one({
            "_id": ObjectId(service_id),
            "owner_id": session.get('user_id')
        })
        
        if not service:
            return jsonify({'success': False, 'error': 'Service not found or unauthorized'}), 404
        
        # Update the service with new coordinates
        database.services.update_one(
            {"_id": ObjectId(service_id)},
            {"$set": {
                "lat": lat,
                "lng": lng,
                "location": {
                    "type": "Point",
                    "coordinates": [float(lng), float(lat)]
                }
            }}
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/toggle_save_service', methods=['POST'])
def toggle_save_service():
    """API endpoint to save or unsave a service"""
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    if session.get('role') != 'customer':
        return jsonify({'success': False, 'error': 'Only customers can save services'}), 403
    
    service_id = request.form.get('service_id')
    
    if not service_id:
        return jsonify({'success': False, 'error': 'Service ID required'}), 400
    
    try:
        database = get_db()
        user_id = session.get('user_id')
        
        # Get current user
        user = database.customers.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            # Try providers collection
            user = database.providers.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        # Get saved_services list, initialize if doesn't exist
        saved_services = user.get('saved_services', [])
        
        # Check if service is already saved
        service_id_str = str(service_id)
        if service_id_str in saved_services:
            # Unsave the service
            saved_services.remove(service_id_str)
            saved = False
        else:
            # Save the service
            saved_services.append(service_id_str)
            saved = True
        
        # Update user's saved_services
        if session.get('role') == 'customer':
            database.customers.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"saved_services": saved_services}}
            )
        
        return jsonify({'success': True, 'saved': saved})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/get_saved_services', methods=['GET'])
def get_saved_services():
    """API endpoint to get all saved services for the current user"""
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    if session.get('role') != 'customer':
        return jsonify({'success': False, 'error': 'Only customers can have saved services'}), 403
    
    try:
        database = get_db()
        user_id = session.get('user_id')
        
        # Get current user
        user = database.customers.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        # Get saved_services list
        saved_services = user.get('saved_services', [])
        
        # Get service details for each saved service
        services = []
        for service_id in saved_services:
            service = database.services.find_one({"_id": ObjectId(service_id), "status": "approved"})
            if service:
                services.append({
                    "_id": str(service["_id"]),
                    "name": service.get("name", ""),
                    "category": service.get("category", ""),
                    "area_name": service.get("area_name", ""),
                    "image": service.get("image", ""),
                    "phone": service.get("phone", ""),
                    "rating": service.get("avg_rating", 0)
                })
        
        return jsonify({'success': True, 'services': services})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    debug_mode = os.environ.get('DEBUG', 'True').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
