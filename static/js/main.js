// AreaAssist Main JavaScript

// Get current location and redirect to search
function getCurrentLocation() {
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            function(position) {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                const url = window.location.origin + '/search?lat=' + lat + '&lng=' + lng;
                window.location.href = url;
            },
            function(error) {
                alert('Unable to get your location. Please enable location services or enter pincode manually.');
            }
        );
    } else {
        alert('Geolocation is not supported by your browser. Please use pincode search.');
    }
}

// Get location and fill form fields
function getLocation() {
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            function(position) {
                document.getElementById('lat').value = position.coords.latitude.toFixed(6);
                document.getElementById('lng').value = position.coords.longitude.toFixed(6);
                alert('Location captured!');
            },
            function(error) {
                alert('Unable to get your location. Please enter coordinates manually.');
            }
        );
    } else {
        alert('Geolocation is not supported by your browser.');
    }
}

// Initialize map (placeholder for future Google Maps/Leaflet integration)
function initMap(containerId, lat, lng) {
    const mapContainer = document.getElementById(containerId);
    if (mapContainer) {
        mapContainer.innerHTML = `
            <div class="d-flex align-items-center justify-content-center h-100">
                <div class="text-center">
                    <i class="fas fa-map-marked-alt fa-3x text-muted mb-3"></i>
                    <p class="text-muted">Map: ${lat}, ${lng}</p>
                </div>
            </div>
        `;
    }
}

// Format distance
function formatDistance(meters) {
    if (meters >= 1000) {
        return (meters / 1000).toFixed(1) + ' km';
    }
    return Math.round(meters) + ' m';
}

// Auto-hide alerts after 5 seconds (except sticky alerts)
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        const alerts = document.querySelectorAll('.alert:not(.alert-sticky):not(.alert-inactive)');
        alerts.forEach(function(alert) {
            alert.classList.add('fade');
            setTimeout(function() {
                alert.remove();
            }, 500);
        });
    }, 5000);
});

// Initialize tooltips
var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
var tooltipList = tooltipTriggerList.map(function(tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
});

// Password visibility toggle
function initPasswordToggles() {
    // Toggle for main password field (login and register)
    const togglePassword = document.getElementById('togglePassword');
    if (togglePassword) {
        togglePassword.addEventListener('click', function() {
            const passwordInput = document.getElementById('password');
            const passwordIcon = document.getElementById('passwordIcon');
            if (passwordInput.type === 'password') {
                passwordInput.type = 'text';
                passwordIcon.classList.remove('fa-eye');
                passwordIcon.classList.add('fa-eye-slash');
            } else {
                passwordInput.type = 'password';
                passwordIcon.classList.remove('fa-eye-slash');
                passwordIcon.classList.add('fa-eye');
            }
        });
    }
    
    // Toggle for confirm password field (register)
    const toggleConfirmPassword = document.getElementById('toggleConfirmPassword');
    if (toggleConfirmPassword) {
        toggleConfirmPassword.addEventListener('click', function() {
            const confirmPasswordInput = document.getElementById('confirmPassword');
            const confirmPasswordIcon = document.getElementById('confirmPasswordIcon');
            if (confirmPasswordInput.type === 'password') {
                confirmPasswordInput.type = 'text';
                confirmPasswordIcon.classList.remove('fa-eye');
                confirmPasswordIcon.classList.add('fa-eye-slash');
            } else {
                confirmPasswordInput.type = 'password';
                confirmPasswordIcon.classList.remove('fa-eye-slash');
                confirmPasswordIcon.classList.add('fa-eye');
            }
        });
    }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    initPasswordToggles();
});

// Password validation for registration
function validatePasswords() {
    const password = document.getElementById('password');
    const confirmPassword = document.getElementById('confirmPassword');
    
    if (password && confirmPassword) {
        const registerForm = password.closest('form');
        if (registerForm) {
            registerForm.addEventListener('submit', function(e) {
                if (password.value !== confirmPassword.value) {
                    e.preventDefault();
                    alert('Passwords do not match!');
                    confirmPassword.focus();
                    return false;
                }
                if (password.value.length < 6) {
                    e.preventDefault();
                    alert('Password must be at least 6 characters!');
                    password.focus();
                    return false;
                }
            });
        }
    }
}
