const socket = io();
let employeeChart, guestChart, roomChart;

// SocketIO event listeners for real-time updates
socket.on('attendance_update', (data) => {
    console.log('Attendance update received:', data);
    showToast(`${data.name || 'User'} ${data.action === 'check-in' ? 'checked in' : 'checked out'} at ${data.time_in || data.time_out || 'N/A'}`);
    loadAttendance();
});
socket.on('guest_update', (data) => {
    console.log('Guest update received:', data);
    showToast(`${data.name || 'Guest'} ${data.action === 'check-in' ? 'checked in' : 'checked out'}`);
    loadGuestRecords();
});
socket.on('room_status_update', () => {
    console.log('Room status update received');
    updateRoomStatus();
});
socket.on('analytics_update', (data) => {
    console.log('Analytics update received:', data);
    updateCharts(data);
});

// DOM elements
const attendanceTableBody = document.getElementById('attendanceTableBody');
const guestTableBody = document.getElementById('guestTableBody');
const roomStatusTableBody = document.getElementById('roomStatusTableBody');
const employeeForm = document.getElementById('employee-form');
const guestForm = document.getElementById('guest-form');
const bookingForm = document.getElementById('booking-form');
const addEmployeeForm = document.getElementById('addEmployeeForm');
const employeeLoginSection = document.getElementById('employeeLoginSection');
const guestLoginSection = document.getElementById('guestLoginSection');
const attendanceSection = document.getElementById('attendanceSection');
const guestSection = document.getElementById('guestSection');
const roomAvailabilitySection = document.getElementById('roomAvailabilitySection');
const roomAvailabilityStatus = document.getElementById('roomAvailabilityStatus');
const employeeQrCodeContainer = document.getElementById('employeeQrCodeContainer');
const guestQrCodeContainer = document.getElementById('guestQrCodeContainer');
const checkInBtn = document.getElementById('checkInBtn');
const checkOutBtn = document.getElementById('checkOutBtn');
const guestCheckInBtn = document.getElementById('guestCheckInBtn');
const guestCheckOutBtn = document.getElementById('guestCheckOutBtn');
const refreshAttendanceBtn = document.getElementById('refreshAttendanceBtn');
const filterAttendanceBtn = document.getElementById('filterAttendanceBtn');
const exportBtn = document.getElementById('exportBtn');
const refreshGuestRecordsBtn = document.getElementById('refreshGuestRecordsBtn');
const syncChannelsBtn = document.getElementById('syncChannelsBtn');
const employeeBiometricLogin = document.getElementById('employeeBiometricLogin');
const guestBiometricLogin = document.getElementById('guestBiometricLogin');
const employeeQrLogin = document.getElementById('employeeQrLogin');
const guestQrLogin = document.getElementById('guestQrLogin');
const generateInvoiceBtn = document.getElementById('generateInvoiceBtn');
const employeeTabNav = document.getElementById('employeeTabNav');
const bookingTabNav = document.getElementById('bookingTabNav');
const guestTabNav = document.getElementById('guestTabNav');
const skeletonLoader = document.querySelector('.skeleton-loader');
const employeeChartFilterBtn = document.getElementById('employeeChartFilterBtn');
const guestChartFilterBtn = document.getElementById('guestChartFilterBtn');
const roomChartFilterBtn = document.getElementById('roomChartFilterBtn');
const totalUsers = document.getElementById('total-users');
const activeBookings = document.getElementById('active-bookings');
const totalGuests = document.getElementById('total-guests');

// State variables
let hasLoggedIn = {{ hasLoggedIn | tojson | safe }};
let userRole = '{{ userRole | safe }}' || 'guest';
let username = {{ username | tojson | safe }};
let currentRecordsPage = {{ records_pagination.current_page or 1 }};
let currentRecordsPerPage = {{ records_pagination.per_page or 50 }};
let currentRoomsPage = {{ rooms_pagination.current_page or 1 }};
let currentRoomsPerPage = {{ rooms_pagination.per_page or 50 }};
let currentGuestsPage = {{ guests_pagination.current_page or 1 }};
let currentGuestsPerPage = {{ guests_pagination.per_page or 50 }};

function validateInput(input) {
    input.value = input.value.replace(/[<>"';&]/g, '');
    return input.value;
}

function searchTable(input) {
    const table = input.closest('.table-wrapper').querySelector('table');
    const rows = table.querySelectorAll('tbody tr');
    const query = input.value.toLowerCase();
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(query) ? '' : 'none';
    });
}

function sortTable(th) {
    const table = th.closest('table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const index = Array.from(th.parentElement.children).indexOf(th);
    const asc = th.dataset.order !== 'asc';
    th.dataset.order = asc ? 'asc' : 'desc';
    rows.sort((a, b) => {
        const aText = a.children[index].textContent.trim();
        const bText = b.children[index].textContent.trim();
        return asc ? aText.localeCompare(bText, undefined, { numeric: true }) : bText.localeCompare(aText, undefined, { numeric: true });
    });
    tbody.innerHTML = '';
    rows.forEach(row => tbody.appendChild(row));
}

function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast align-items-center text-white bg-primary border-0';
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;
    document.body.appendChild(toast);
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    setTimeout(() => toast.remove(), 3000);
}

function updateUi() {
    const welcomeTitle = document.getElementById('welcome-title');
    const welcomeMessage = document.getElementById('welcome-message');
    if (hasLoggedIn) {
        if (userRole === 'admin') {
            welcomeTitle.textContent = 'Admin Control Panel';
            welcomeMessage.textContent = 'Manage your organization, employees, and bookings with full control';
            employeeTabNav.classList.remove('hidden');
            bookingTabNav.classList.remove('hidden');
            guestTabNav.classList.remove('hidden');
            attendanceSection.classList.remove('hidden');
            bookingForm.classList.remove('hidden');
            roomAvailabilitySection.classList.remove('hidden');
            generateInvoiceBtn.classList.remove('hidden');
            guestSection.classList.remove('hidden');
            employeeLoginSection.classList.add('hidden');
            guestLoginSection.classList.add('hidden');
        } else if (userRole === 'employee') {
            welcomeTitle.textContent = 'Employee Dashboard';
            welcomeMessage.textContent = 'Handle check-ins and view attendance records';
            employeeTabNav.classList.remove('hidden');
            bookingTabNav.classList.add('hidden');
            guestTabNav.classList.add('hidden');
            attendanceSection.classList.remove('hidden');
            employeeLoginSection.classList.add('hidden');
            guestLoginSection.classList.add('hidden');
            bookingForm.classList.add('hidden');
            guestSection.classList.add('hidden');
        } else if (userRole === 'guest') {
            welcomeTitle.textContent = 'Guest Portal';
            welcomeMessage.textContent = 'Book rooms and manage your stay with ease';
            employeeTabNav.classList.add('hidden');
            bookingTabNav.classList.remove('hidden');
            guestTabNav.classList.remove('hidden');
            bookingForm.classList.remove('hidden');
            guestLoginSection.classList.add('hidden');
            guestSection.classList.remove('hidden');
            attendanceSection.classList.add('hidden');
            employeeLoginSection.classList.add('hidden');
        }
    } else {
        welcomeTitle.textContent = 'Welcome to Your Management Portal';
        welcomeMessage.textContent = 'Please log in or register to access your personalized dashboard';
        employeeTabNav.classList.remove('hidden');
        bookingTabNav.classList.remove('hidden');
        guestTabNav.classList.remove('hidden');
        employeeLoginSection.classList.remove('hidden');
        guestLoginSection.classList.remove('hidden');
        attendanceSection.classList.add('hidden');
        bookingForm.classList.add('hidden');
        roomAvailabilitySection.classList.add('hidden');
        generateInvoiceBtn.classList.add('hidden');
        guestSection.classList.add('hidden');
    }

    const defaultTab = hasLoggedIn && (userRole === 'admin' || userRole === 'employee') ? '#employee-tab' : '#booking-tab';
    $(`#myTab a[href="${defaultTab}"]`).tab('show');

    loadAttendance();
    loadGuestRecords();
    updateRoomStatus();
    checkRoomAvailability();
    loadCharts();
    if (hasLoggedIn) loadDashboardData();
}

async function loadDashboardData() {
    if (!hasLoggedIn) return;
    skeletonLoader.classList.add('visible');
    try {
        const response = await fetch('/dashboard/data', {
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            totalUsers.textContent = data.total_users || 0;
            activeBookings.textContent = data.active_bookings || 0;
            totalGuests.textContent = data.total_guests || 0;
        } else {
            showToast('Failed to load dashboard data');
        }
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        showToast('Error loading dashboard data');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
}

async function loadAttendance(page = currentRecordsPage, perPage = currentRecordsPerPage) {
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'employee')) return;
    skeletonLoader.classList.add('visible');
    const startDate = document.getElementById('startDate').value || new Date().toISOString().split('T')[0];
    const endDate = document.getElementById('endDate').value || startDate;
    try {
        const response = await fetch(`/attendance?page=${page}&per_page=${perPage}&start_date=${startDate}&end_date=${endDate}`, { credentials: 'include' });
        const data = await response.json();
        attendanceTableBody.innerHTML = '';
        if (data.success && data.records?.length) {
            data.records.forEach(record => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${record.employee_id || 'N/A'}</td>
                    <td>${record.name || 'N/A'}</td>
                    <td>${record.date || '-'}</td>
                    <td>${record.time_in || '-'}</td>
                    <td>${record.time_out || '-'}</td>
                `;
                attendanceTableBody.appendChild(row);
            });
            currentRecordsPage = data.pagination.current_page;
            currentRecordsPerPage = data.pagination.per_page;
            updateAttendancePagination(data.pagination);
        } else {
            attendanceTableBody.innerHTML = '<tr><td colspan="5">No attendance records found</td></tr>';
            updateAttendancePagination({ current_page: 1, per_page: perPage, total_items: 0, total_pages: 1 });
        }
    } catch (error) {
        console.error('Error loading attendance:', error);
        showToast('Error loading attendance records');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
}

function updateAttendancePagination(pagination) {
    const paginationContainer = document.getElementById('attendancePagination');
    paginationContainer.innerHTML = `
        <span class="pagination-info">
            Page ${pagination.current_page} of ${pagination.total_pages} (${pagination.total_items} items)
        </span>
        <button class="page-link ${pagination.current_page === 1 ? 'disabled' : ''}" 
                onclick="loadAttendance(${pagination.current_page - 1}, ${pagination.per_page})" aria-label="Previous">
            Previous
        </button>
        ${Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map(page => `
            <button class="page-link ${page === pagination.current_page ? 'active' : ''}" 
                    onclick="loadAttendance(${page}, ${pagination.per_page})" aria-label="Page ${page}">
                ${page}
            </button>
        `).join('')}
        <button class="page-link ${pagination.current_page === pagination.total_pages ? 'disabled' : ''}" 
                onclick="loadAttendance(${pagination.current_page + 1}, ${pagination.per_page})" aria-label="Next">
            Next
        </button>
    `;
}

async function loadGuestRecords(page = currentGuestsPage, perPage = currentGuestsPerPage) {
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'guest')) return;
    skeletonLoader.classList.add('visible');
    try {
        const response = await fetch(`/dashboard?page=${page}&per_page=${perPage}§ion=guests`, { credentials: 'include' });
        const data = await response.json();
        guestTableBody.innerHTML = '';
        if (data.success && data.guests?.length) {
            data.guests.forEach(record => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${record.guest_id || 'N/A'}</td>
                    <td>${record.name || 'N/A'}</td>
                    <td>${record.room_id || 'N/A'}</td>
                    <td>${record.check_in_date || '-'}</td>
                    <td>${record.check_out_date || '-'}</td>
                    <td>${record.status || 'N/A'}</td>
                `;
                guestTableBody.appendChild(row);
            });
            currentGuestsPage = data.pagination.current_page;
            currentGuestsPerPage = data.pagination.per_page;
            updateGuestPagination(data.pagination);
        } else {
            guestTableBody.innerHTML = '<tr><td colspan="6">No guest records found</td></tr>';
            updateGuestPagination({ current_page: 1, per_page: perPage, total_items: 0, total_pages: 1 });
        }
    } catch (error) {
        console.error('Error loading guest records:', error);
        showToast('Error loading guest records');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
}

function updateGuestPagination(pagination) {
    const paginationContainer = document.getElementById('guestPagination');
    paginationContainer.innerHTML = `
        <span class="pagination-info">
            Page ${pagination.current_page} of ${pagination.total_pages} (${pagination.total_items} items)
        </span>
        <button class="page-link ${pagination.current_page === 1 ? 'disabled' : ''}" 
                onclick="loadGuestRecords(${pagination.current_page - 1}, ${pagination.per_page})" aria-label="Previous">
            Previous
        </button>
        ${Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map(page => `
            <button class="page-link ${page === pagination.current_page ? 'active' : ''}" 
                    onclick="loadGuestRecords(${page}, ${pagination.per_page})" aria-label="Page ${page}">
                ${page}
            </button>
        `).join('')}
        <button class="page-link ${pagination.current_page === pagination.total_pages ? 'disabled' : ''}" 
                onclick="loadGuestRecords(${pagination.current_page + 1}, ${pagination.per_page})" aria-label="Next">
            Next
        </button>
    `;
}

async function checkRoomAvailability() {
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'guest')) return;
    const checkInDate = document.getElementById('checkInDateInput').value;
    const checkOutDate = document.getElementById('checkOutDateInput').value;
    const roomType = document.getElementById('roomTypeSelect').value;
    if (!checkInDate || !checkOutDate || !roomType) {
        roomAvailabilityStatus.textContent = 'Please complete all booking details';
        return;
    }
    try {
        const response = await fetch(`/room_availability?check_in_date=${checkInDate}&check_out_date=${checkOutDate}&room_type=${roomType}`, { credentials: 'include' });
        const data = await response.json();
        roomAvailabilityStatus.textContent = data.success && data.available ? `Available rooms: ${data.rooms.length}` : 'No rooms available';
    } catch (error) {
        console.error('Error checking room availability:', error);
        showToast('Error checking availability');
    }
}

async function updateRoomStatus(page = currentRoomsPage, perPage = currentRoomsPerPage) {
    skeletonLoader.classList.add('visible');
    try {
        const response = await fetch(`/room_status?page=${page}&per_page=${perPage}`, { credentials: 'include' });
        const data = await response.json();
        roomStatusTableBody.innerHTML = '';
        if (data.success && data.rooms?.length) {
            data.rooms.forEach(room => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${room.room_id || 'N/A'}</td>
                    <td>${room.room_type || 'N/A'}</td>
                    <td>${room.status || 'N/A'}</td>
                `;
                roomStatusTableBody.appendChild(row);
            });
            currentRoomsPage = data.pagination.current_page;
            currentRoomsPerPage = data.pagination.per_page;
            updateRoomPagination(data.pagination);
        } else {
            roomStatusTableBody.innerHTML = '<tr><td colspan="3">No rooms found</td></tr>';
            updateRoomPagination({ current_page: 1, per_page: perPage, total_items: 0, total_pages: 1 });
        }
    } catch (error) {
        console.error('Error updating room status:', error);
        showToast('Error loading rooms');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
}

function updateRoomPagination(pagination) {
    const paginationContainer = document.getElementById('roomPagination');
    paginationContainer.innerHTML = `
        <span class="pagination-info">
            Page ${pagination.current_page} of ${pagination.total_pages} (${pagination.total_items} items)
        </span>
        <button class="page-link ${pagination.current_page === 1 ? 'disabled' : ''}" 
                onclick="updateRoomStatus(${pagination.current_page - 1}, ${pagination.per_page})" aria-label="Previous">
            Previous
        </button>
        ${Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map(page => `
            <button class="page-link ${page === pagination.current_page ? 'active' : ''}" 
                    onclick="updateRoomStatus(${page}, ${pagination.per_page})" aria-label="Page ${page}">
                ${page}
            </button>
        `).join('')}
        <button class="page-link ${pagination.current_page === pagination.total_pages ? 'disabled' : ''}" 
                onclick="updateRoomStatus(${pagination.current_page + 1}, ${pagination.per_page})" aria-label="Next">
            Next
        </button>
    `;
}

async function loadCharts(startDate = '', endDate = '') {
    try {
        const query = startDate && endDate ? `?start_date=${startDate}&end_date=${endDate}` : '';
        const response = await fetch(`/analytics?page=1&per_page=30${query}`, { credentials: 'include' });
        const data = await response.json();
        if (data.success && data.trends) {
            // Employee Chart
            if (employeeChart) employeeChart.destroy();
            const employeeCtx = document.getElementById('employeeChart').getContext('2d');
            employeeChart = new Chart(employeeCtx, {
                type: 'line',
                data: {
                    labels: data.trends.map(t => t.date),
                    datasets: [{
                        label: 'Active Employees',
                        data: data.trends.map(t => t.active_employees || 0),
                        borderColor: '#007bff',
                        backgroundColor: 'rgba(0, 123, 255, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: { beginAtZero: true, title: { display: true, text: 'Number of Employees' } },
                        x: { title: { display: true, text: 'Date' } }
                    },
                    plugins: {
                        legend: { display: true }
                    }
                }
            });

            // Guest Chart
            if (guestChart) guestChart.destroy();
            const guestCtx = document.getElementById('guestChart').getContext('2d');
            guestChart = new Chart(guestCtx, {
                type: 'line',
                data: {
                    labels: data.trends.map(t => t.date),
                    datasets: [{
                        label: 'Guest Check-Ins',
                        data: data.trends.map(t => t.guest_check_ins || 0),
                        borderColor: '#28a745',
                        backgroundColor: 'rgba(40, 167, 69, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: { beginAtZero: true, title: { display: true, text: 'Number of Check-Ins' } },
                        x: { title: { display: true, text: 'Date' } }
                    },
                    plugins: {
                        legend: { display: true }
                    }
                }
            });

            // Room Chart
            if (roomChart) roomChart.destroy();
            const roomCtx = document.getElementById('roomChart').getContext('2d');
            roomChart = new Chart(roomCtx, {
                type: 'bar',
                data: {
                    labels: ['Standard', 'Deluxe', 'Suite'],
                    datasets: [{
                        label: 'Room Occupancy',
                        data: [
                            data.trends.reduce((sum, t) => sum + (t.room_occupancy?.standard || 0), 0) / (data.trends.length || 1),
                            data.trends.reduce((sum, t) => sum + (t.room_occupancy?.deluxe || 0), 0) / (data.trends.length || 1),
                            data.trends.reduce((sum, t) => sum + (t.room_occupancy?.suite || 0), 0) / (data.trends.length || 1)
                        ],
                        backgroundColor: ['rgba(255, 99, 132, 0.2)', 'rgba(54, 162, 235, 0.2)', 'rgba(255, 206, 86, 0.2)'],
                        borderColor: ['rgba(255, 99, 132, 1)', 'rgba(54, 162, 235, 1)', 'rgba(255, 206, 86, 1)'],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: { beginAtZero: true, title: { display: true, text: 'Average Occupancy' } },
                        x: { title: { display: true, text: 'Room Type' } }
                    },
                    plugins: {
                        legend: { display: true }
                    }
                }
            });
        } else {
            showToast('Failed to load analytics data');
        }
    } catch (error) {
        console.error('Error loading charts:', error);
        showToast('Error loading analytics charts');
    }
}

function updateCharts(data) {
    if (!data.trends) return;
    const employeeStartDate = document.getElementById('employeeChartStartDate').value;
    const employeeEndDate = document.getElementById('employeeChartEndDate').value;
    const guestStartDate = document.getElementById('guestChartStartDate').value;
    const guestEndDate = document.getElementById('guestChartEndDate').value;
    const roomStartDate = document.getElementById('roomChartStartDate').value;
    const roomEndDate = document.getElementById('roomChartEndDate').value;

    const filterByDate = (trends, startDate, endDate) => {
        if (!startDate || !endDate) return trends;
        return trends.filter(t => {
            const date = new Date(t.date);
            return date >= new Date(startDate) && date <= new Date(endDate);
        });
    };

    // Update Employee Chart
    if (employeeChart) {
        const employeeData = filterByDate(data.trends, employeeStartDate, employeeEndDate);
        employeeChart.data.labels = employeeData.map(t => t.date);
        employeeChart.data.datasets[0].data = employeeData.map(t => t.active_employees || 0);
        employeeChart.update();
    }

    // Update Guest Chart
    if (guestChart) {
        const guestData = filterByDate(data.trends, guestStartDate, guestEndDate);
        guestChart.data.labels = guestData.map(t => t.date);
        guestChart.data.datasets[0].data = guestData.map(t => t.guest_check_ins || 0);
        guestChart.update();
    }

    // Update Room Chart
    if (roomChart) {
        const roomData = filterByDate(data.trends, roomStartDate, roomEndDate);
        roomChart.data.datasets[0].data = [
            roomData.reduce((sum, t) => sum + (t.room_occupancy?.standard || 0), 0) / (roomData.length || 1),
            roomData.reduce((sum, t) => sum + (t.room_occupancy?.deluxe || 0), 0) / (roomData.length || 1),
            roomData.reduce((sum, t) => sum + (t.room_occupancy?.suite || 0), 0) / (roomData.length || 1)
        ];
        roomChart.update();
    }
}

async function generateQrCode(container, role) {
    try {
        const response = await fetch(`/generate_qr?role=${role}`, { credentials: 'include' });
        const data = await response.json();
        if (data.success && data.qr_code) {
            container.innerHTML = '';
            container.classList.remove('hidden');
            QRCode.toCanvas(data.qr_code, { width: 200 }, (err, canvas) => {
                if (err) throw err;
                container.appendChild(canvas);
            });
        } else {
            showToast(data.message || 'Failed to generate QR code');
        }
    } catch (error) {
        console.error('QR code error:', error);
        showToast('Error generating QR code');
    }
}

async function handleLogin(form, role) {
    const username = form.querySelector('[name="username"]').value;
    const password = form.querySelector('[name="password"]').value;
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, role }),
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            hasLoggedIn = true;
            userRole = data.role;
            username = data.username;
            showToast('Login successful');
            updateUi();
        } else {
            showToast(data.message || 'Login failed');
        }
    } catch (error) {
        console.error(`${role} login error:`, error);
        showToast('Login error. Try again');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
}

employeeForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleLogin(employeeForm, 'employee');
});

guestForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleLogin(guestForm, 'guest');
});

employeeBiometricLogin?.addEventListener('click', async (e) => {
    e.preventDefault();
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/login?method=biometric', { credentials: 'include' });
        const data = await response.json();
        if (data.success) {
            hasLoggedIn = true;
            userRole = data.role;
            username = data.username;
            showToast('Biometric login successful');
            updateUi();
        } else {
            showToast(data.message || 'Biometric login failed');
        }
    } catch (error) {
        console.error('Biometric login error:', error);
        showToast('Biometric login error');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

guestBiometricLogin?.addEventListener('click', async (e) => {
    e.preventDefault();
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/login?method=biometric', { credentials: 'include' });
        const data = await response.json();
        if (data.success) {
            hasLoggedIn = true;
            userRole = data.role;
            username = data.username;
            showToast('Biometric login successful');
            updateUi();
        } else {
            showToast(data.message || 'Biometric login failed');
        }
    } catch (error) {
        console.error('Biometric login error:', error);
        showToast('Biometric login error');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

employeeQrLogin?.addEventListener('click', (e) => {
    e.preventDefault();
    generateQrCode(employeeQrCodeContainer, 'employee');
});

guestQrLogin?.addEventListener('click', (e) => {
    e.preventDefault();
    generateQrCode(guestQrCodeContainer, 'guest');
});

checkInBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'employee')) {
        showToast('Access denied');
        return;
    }
    const employeeId = document.getElementById('employeeId').value;
    const employeeName = document.getElementById('employeeName').value;
    if (!employeeId || !employeeName) {
        showToast('Please provide both Employee ID and Name');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/check_in', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ employee_id: employeeId, name: employeeName }),
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            showToast('Check-in successful');
            loadAttendance();
        } else {
            showToast(data.message || 'Check-in failed');
        }
    } catch (error) {
        console.error('Check-in error:', error);
        showToast('Error during check-in');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

checkOutBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'employee')) {
        showToast('Access denied');
        return;
    }
    const employeeId = document.getElementById('employeeId').value;
    const employeeName = document.getElementById('employeeName').value;
    if (!employeeId || !employeeName) {
        showToast('Please provide both Employee ID and Name');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/check_out', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ employee_id: employeeId, name: employeeName }),
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            showToast('Check-out successful');
            loadAttendance();
        } else {
            showToast(data.message || 'Check-out failed');
        }
    } catch (error) {
        console.error('Check-out error:', error);
        showToast('Error during check-out');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

guestCheckInBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'guest')) {
        showToast('Access denied');
        return;
    }
    const guestId = document.getElementById('guestIdInput').value;
    const guestName = document.getElementById('guestNameInput').value;
    if (!guestId || !guestName) {
        showToast('Please provide both Guest ID and Name');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/guest_check_in', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guest_id: guestId, name: guestName }),
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            showToast('Guest check-in successful');
            loadGuestRecords();
        } else {
            showToast(data.message || 'Guest check-in failed');
        }
    } catch (error) {
        console.error('Guest check-in error:', error);
        showToast('Error during guest check-in');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

guestCheckOutBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'guest')) {
        showToast('Access denied');
        return;
    }
    const guestId = document.getElementById('guestIdInput').value;
    const guestName = document.getElementById('guestNameInput').value;
    if (!guestId || !guestName) {
        showToast('Please provide both Guest ID and Name');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/guest_check_out', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guest_id: guestId, name: guestName }),
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            showToast('Guest check-out successful');
            loadGuestRecords();
        } else {
            showToast(data.message || 'Guest check-out failed');
        }
    } catch (error) {
        console.error('Guest check-out error:', error);
        showToast('Error during guest check-out');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

bookingForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'guest')) {
        showToast('Access denied');
        return;
    }
    const guestName = document.getElementById('guestNameInput').value;
    const checkInDate = document.getElementById('checkInDateInput').value;
    const checkOutDate = document.getElementById('checkOutDateInput').value;
    const roomType = document.getElementById('roomTypeSelect').value;
    if (!guestName || !checkInDate || !checkOutDate || !roomType) {
        showToast('Please complete all booking details');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/book_room', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guest_name: guestName, check_in_date: checkInDate, check_out_date: checkOutDate, room_type: roomType }),
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            showToast('Room booked successfully');
            updateRoomStatus();
            checkRoomAvailability();
        } else {
            showToast(data.message || 'Booking failed');
        }
    } catch (error) {
        console.error('Booking error:', error);
        showToast('Error during booking');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

addEmployeeForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || userRole !== 'admin') {
        showToast('Access denied');
        return;
    }
    const employeeName = document.getElementById('employeeName').value;
    const employeeEmail = document.getElementById('employeeEmail').value;
    if (!employeeName || !employeeEmail) {
        showToast('Please provide both Employee Name and Email');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/add_employee', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: employeeName, email: employeeEmail }),
            credentials: 'include'
        });
        const data = await response.json();
        if (data.success) {
            showToast('Employee added successfully');
            bootstrap.Modal.getInstance(document.getElementById('addEmployeeModal')).hide();
        } else {
            showToast(data.message || 'Failed to add employee');
        }
    } catch (error) {
        console.error('Add employee error:', error);
        showToast('Error adding employee');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

filterAttendanceBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    loadAttendance();
});

refreshAttendanceBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('startDate').value = '';
    document.getElementById('endDate').value = '';
    loadAttendance();
});

exportBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'employee')) {
        showToast('Access denied');
        return;
    }
    const startDate = document.getElementById('startDate').value || new Date().toISOString().split('T')[0];
    const endDate = document.getElementById('endDate').value || startDate;
    try {
        const response = await fetch(`/export_attendance?start_date=${startDate}&end_date=${endDate}`, { credentials: 'include' });
        const data = await response.blob();
        const url = window.URL.createObjectURL(data);
        const a = document.createElement('a');
        a.href = url;
        a.download = `attendance_${startDate}_${endDate}.csv`;
        a.click();
        window.URL.revokeObjectURL(url);
        showToast('Attendance exported successfully');
    } catch (error) {
        console.error('Export error:', error);
        showToast('Error exporting attendance');
    }
});

refreshGuestRecordsBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    loadGuestRecords();
});

syncChannelsBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'guest')) {
        showToast('Access denied');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/sync_channels', { method: 'POST', credentials: 'include' });
        const data = await response.json();
        if (data.success) {
            showToast('Channels synced successfully');
            loadGuestRecords();
        } else {
            showToast(data.message || 'Sync failed');
        }
    } catch (error) {
        console.error('Sync error:', error);
        showToast('Error syncing channels');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

generateInvoiceBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!hasLoggedIn || (userRole !== 'admin' && userRole !== 'guest')) {
        showToast('Access denied');
        return;
    }
    const guestName = document.getElementById('guestNameInput').value;
    const checkInDate = document.getElementById('checkInDateInput').value;
    const checkOutDate = document.getElementById('checkOutDateInput').value;
    const roomType = document.getElementById('roomTypeSelect').value;
    if (!guestName || !checkInDate || !checkOutDate || !roomType) {
        showToast('Please complete all booking details');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        const response = await fetch('/generate_invoice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guest_name: guestName, check_in_date: checkInDate, check_out_date: checkOutDate, room_type: roomType }),
            credentials: 'include'
        });
        const data = await response.blob();
        const url = window.URL.createObjectURL(data);
        const a = document.createElement('a');
        a.href = url;
        a.download = `invoice_${guestName}_${checkInDate}.pdf`;
        a.click();
        window.URL.revokeObjectURL(url);
        showToast('Invoice generated successfully');
    } catch (error) {
        console.error('Invoice generation error:', error);
        showToast('Error generating invoice');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

employeeChartFilterBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    const startDate = document.getElementById('employeeChartStartDate').value;
    const endDate = document.getElementById('employeeChartEndDate').value;
    if (!startDate || !endDate) {
        showToast('Please select both start and end dates');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        await loadCharts(startDate, endDate);
        showToast('Employee chart updated');
    } catch (error) {
        console.error('Error filtering employee chart:', error);
        showToast('Error updating employee chart');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

guestChartFilterBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    const startDate = document.getElementById('guestChartStartDate').value;
    const endDate = document.getElementById('guestChartEndDate').value;
    if (!startDate || !endDate) {
        showToast('Please select both start and end dates');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        await loadCharts(startDate, endDate);
        showToast('Guest chart updated');
    } catch (error) {
        console.error('Error filtering guest chart:', error);
        showToast('Error updating guest chart');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

roomChartFilterBtn?.addEventListener('click', async (e) => {
    e.preventDefault();
    const startDate = document.getElementById('roomChartStartDate').value;
    const endDate = document.getElementById('roomChartEndDate').value;
    if (!startDate || !endDate) {
        showToast('Please select both start and end dates');
        return;
    }
    try {
        skeletonLoader.classList.add('visible');
        await loadCharts(startDate, endDate);
        showToast('Room chart updated');
    } catch (error) {
        console.error('Error filtering room chart:', error);
        showToast('Error updating room chart');
    } finally {
        skeletonLoader.classList.remove('visible');
    }
});

// Initialize the UI on page load
document.addEventListener('DOMContentLoaded', () => {
    updateUi();
});