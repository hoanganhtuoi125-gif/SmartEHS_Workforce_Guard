// =========================================================
// SMART EHS - MODERN WEB APPLICATION JAVASCRIPT
// =========================================================

let currentTab = 'tab-dashboard';
let cachedEmployees = [];
let cachedViolations = [];
let cachedStrangers = [];

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initClock();
    initDashboardFeed();
    initEmployeesHub();
    initStrangersHub();
    initViolationsHub();
    initSettingsHub();
    initModals();
    initCamZoomEvents();
    loadInitialVoiceState();

    // Tự động cập nhật số liệu mỗi 3 giây
    setInterval(fetchRealtimeStats, 3000);
});

// =========================================================
// NAVIGATION & CLOCK
// =========================================================
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');
            switchTab(targetTab);
        });
    });

    document.getElementById('btn-manual-refresh').addEventListener('click', () => {
        fetchRealtimeStats();
        loadCurrentTabData();
        showToast('Đã làm mới dữ liệu hệ thống', 'info');
    });
}

function switchTab(tabId) {
    currentTab = tabId;
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.getAttribute('data-tab') === tabId);
    });

    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.id === tabId);
    });

    const titles = {
        'tab-dashboard': 'Bảng Điều Khiển Giám Sát',
        'tab-cameras': 'Khung Nhìn Trực Tiếp 2 Camera',
        'tab-employees': 'Quản Lý Hồ Sơ Nhân Sự',
        'tab-strangers': 'Hồ Sơ Đối Tượng Chưa Đăng Ký',
        'tab-violations': 'Nhật Ký Vi Phạm An Toàn PPE',
        'tab-settings': 'Cấu Hình Hệ Thống & Cảnh Báo Zalo'
    };

    const titleEl = document.getElementById('current-page-title');
    if (titleEl && titles[tabId]) {
        titleEl.textContent = titles[tabId];
    }

    loadCurrentTabData();
}

function loadCurrentTabData() {
    if (currentTab === 'tab-employees') loadEmployees();
    else if (currentTab === 'tab-strangers') loadStrangers();
    else if (currentTab === 'tab-violations') loadViolations();
    else if (currentTab === 'tab-settings') loadSettings();
}

function initClock() {
    const clockEl = document.getElementById('live-clock');
    const update = () => {
        const now = new Date();
        clockEl.innerHTML = `<i class="fa-regular fa-clock"></i> ${now.toTimeString().split(' ')[0]}`;
    };
    update();
    setInterval(update, 1000);
}

// =========================================================
// REALTIME STATS & DASHBOARD
// =========================================================
async function fetchRealtimeStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        if (data.status === 'success') {
            document.getElementById('kpi-attendance').textContent = data.attendance_count;
            document.getElementById('kpi-violations').textContent = data.violation_count;
            document.getElementById('kpi-strangers').textContent = data.stranger_count;
            document.getElementById('kpi-employees').textContent = data.employee_count;
            document.getElementById('badge-stranger-count').textContent = data.stranger_count;

            renderDashboardFeed(data.recent_violations, data.recent_strangers);
        }
    } catch (e) {
        console.warn('Lỗi đồng bộ stats:', e);
    }
}

function initDashboardFeed() {
    fetchRealtimeStats();
}

function renderDashboardFeed(recentViols, recentStrangers) {
    const container = document.getElementById('feed-violations-container');
    if (!container) return;

    const items = [];
    if (recentViols) {
        recentViols.forEach(v => items.push({ type: 'violation', ...v, sortTime: v.time }));
    }
    if (recentStrangers) {
        recentStrangers.forEach(s => items.push({ type: 'stranger', name: '🚨 Người lạ', violation: `Phát hiện tại ${s.location} (${s.ppe || 'PPE'})`, evidence_image: s.image, time: s.time, sortTime: s.time }));
    }

    items.sort((a, b) => b.sortTime.localeCompare(a.sortTime));

    if (items.length === 0) {
        container.innerHTML = `<div class="empty-state" style="padding:24px; text-align:center; color:var(--text-dim);">Chưa ghi nhận sự cố nào hôm nay.</div>`;
        return;
    }

    container.innerHTML = items.slice(0, 8).map(item => {
        const imgSrc = item.evidence_image ? `/media/${item.evidence_image}` : '/static/img/avatar_default.png';
        const isStranger = item.type === 'stranger';
        const badgeColor = isStranger ? 'var(--warning)' : 'var(--danger)';
        const labelText = isStranger ? 'NGƯỜI LẠ' : 'VI PHẠM PPE';

        return `
            <div class="feed-item" onclick="viewImageModal('${imgSrc}', '${item.name} - ${item.time}')">
                <img src="${imgSrc}" class="feed-avatar" alt="Evidence" onerror="this.src='/static/img/avatar_default.png'">
                <div class="feed-info">
                    <div class="feed-header">
                        <span class="feed-name">${escapeHtml(item.name)}</span>
                        <span class="feed-time">${item.time.split(' ')[1] || item.time}</span>
                    </div>
                    <span class="feed-badge" style="color: ${badgeColor};">
                        [${labelText}] ${escapeHtml(item.violation)}
                    </span>
                </div>
            </div>
        `;
    }).join('');
}

// =========================================================
// EMPLOYEES HUB (CRUD)
// =========================================================
function initEmployeesHub() {
    const searchInput = document.getElementById('input-search-emp');
    searchInput.addEventListener('input', () => {
        const q = searchInput.value.toLowerCase().trim();
        const filtered = cachedEmployees.filter(e => 
            e.name.toLowerCase().includes(q) || e.role.toLowerCase().includes(q)
        );
        renderEmployees(filtered);
    });

    document.getElementById('btn-open-add-emp').addEventListener('click', () => {
        openModal('modal-add-employee');
    });

    // Form thêm nhân viên
    const formAdd = document.getElementById('form-add-employee');
    const dropzone = document.getElementById('dropzone-add-emp');
    const fileInput = document.getElementById('add-emp-file');
    const previewContainer = document.getElementById('preview-add-container');
    const previewImg = document.getElementById('img-add-preview');
    const txtFilename = document.getElementById('txt-add-filename');

    dropzone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            const file = fileInput.files[0];
            previewImg.src = URL.createObjectURL(file);
            txtFilename.textContent = file.name;
            previewContainer.style.display = 'flex';
        }
    });

    formAdd.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('add-emp-name').value.trim();
        const role = document.getElementById('add-emp-role').value;
        const file = fileInput.files[0];

        if (!name || !file) {
            showToast('Vui lòng điền họ tên và chọn ảnh chân dung!', 'error');
            return;
        }

        const formData = new FormData();
        formData.append('name', name);
        formData.append('role', role);
        formData.append('image', file);

        const btnSubmit = document.getElementById('btn-submit-add-emp');
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Đang nạp...';

        try {
            const res = await fetch('/api/employees', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(data.message, 'success');
                closeModal('modal-add-employee');
                formAdd.reset();
                previewContainer.style.display = 'none';
                loadEmployees();
                fetchRealtimeStats();
            } else {
                showToast(data.message, 'error');
            }
        } catch (err) {
            showToast('Không thể kết nối tới máy chủ', 'error');
        } finally {
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = '<i class="fa-solid fa-check"></i> Lưu & Nạp Vào AI';
        }
    });

    // Form sửa nhân viên
    const formEdit = document.getElementById('form-edit-employee');
    formEdit.addEventListener('submit', async (e) => {
        e.preventDefault();
        const origName = document.getElementById('edit-emp-original-name').value;
        const newName = document.getElementById('edit-emp-name').value.trim();
        const newRole = document.getElementById('edit-emp-role').value;
        const fileInputEdit = document.getElementById('edit-emp-file');

        const formData = new FormData();
        formData.append('new_name', newName);
        formData.append('new_role', newRole);
        if (fileInputEdit.files.length > 0) {
            formData.append('image', fileInputEdit.files[0]);
        }

        try {
            const res = await fetch(`/api/employees/${encodeURIComponent(origName)}`, {
                method: 'PUT',
                body: formData
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(data.message, 'success');
                closeModal('modal-edit-employee');
                loadEmployees();
            } else {
                showToast(data.message, 'error');
            }
        } catch (err) {
            showToast('Lỗi cập nhật nhân viên', 'error');
        }
    });
}

async function loadEmployees() {
    try {
        const res = await fetch('/api/employees');
        const data = await res.json();
        if (data.status === 'success') {
            cachedEmployees = data.data;
            renderEmployees(cachedEmployees);
        }
    } catch (e) {
        console.error('Lỗi nạp nhân viên:', e);
    }
}

function renderEmployees(list) {
    const container = document.getElementById('employees-grid-container');
    if (!container) return;

    if (list.length === 0) {
        container.innerHTML = `<div class="empty-state" style="grid-column: 1/-1; padding: 40px; text-align: center; color: var(--text-dim);">Chưa có nhân viên nào trong cơ sở dữ liệu. Bấm "Thêm Nhân Viên Mới" để đăng ký.</div>`;
        return;
    }

    container.innerHTML = list.map(emp => {
        const imgSrc = emp.image_path ? `/media/${emp.image_path}` : '/static/img/avatar_default.png';
        return `
            <div class="emp-card">
                <img src="${imgSrc}" class="emp-avatar" alt="${escapeHtml(emp.name)}" onerror="this.src='/static/img/avatar_default.png'">
                <h4 class="emp-name">${escapeHtml(emp.name)}</h4>
                <span class="emp-role">${escapeHtml(emp.role)}</span>
                
                <div class="emp-stats-row">
                    <div class="emp-stat-item">
                        <span>ĐIỂM DANH</span>
                        <b>${emp.att_count}</b>
                    </div>
                    <div class="emp-stat-item">
                        <span>VI PHẠM</span>
                        <b style="color: ${emp.vio_count > 0 ? 'var(--danger)' : 'var(--text-main)'};">${emp.vio_count}</b>
                    </div>
                </div>

                <div class="emp-actions">
                    <button class="btn-emp-action btn-view" onclick="openEmployeeDetail('${escapeHtml(emp.name)}')">
                        <i class="fa-solid fa-eye"></i> Xem
                    </button>
                    <button class="btn-emp-action btn-edit" onclick="openEditEmployee('${escapeHtml(emp.name)}', '${escapeHtml(emp.role)}')">
                        <i class="fa-solid fa-pen"></i> Sửa
                    </button>
                    <button class="btn-emp-action btn-del" onclick="deleteEmployee('${escapeHtml(emp.name)}')">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

async function openEmployeeDetail(name) {
    try {
        const res = await fetch(`/api/employees/${encodeURIComponent(name)}`);
        const data = await res.json();
        if (data.status === 'success') {
            document.getElementById('detail-emp-name').textContent = data.name;
            document.getElementById('detail-emp-role').textContent = data.role;
            document.getElementById('detail-emp-att-c').textContent = data.attendance_logs.length;
            document.getElementById('detail-emp-vio-c').textContent = data.violation_logs.length;
            document.getElementById('detail-emp-avatar').src = data.image_path ? `/media/${data.image_path}` : '/static/img/avatar_default.png';

            // Danh sách điểm danh
            const attList = document.getElementById('detail-att-list');
            if (data.attendance_logs.length === 0) {
                attList.innerHTML = `<li style="color:var(--text-dim); text-align:center;">Chưa có lịch sử điểm danh.</li>`;
            } else {
                attList.innerHTML = data.attendance_logs.map(a => `
                    <li>
                        <span><i class="fa-regular fa-clock"></i> ${a.time}</span>
                        <span style="color:var(--success); font-weight:700;">${escapeHtml(a.ppe)}</span>
                    </li>
                `).join('');
            }

            // Danh sách vi phạm
            const vioList = document.getElementById('detail-vio-list');
            if (data.violation_logs.length === 0) {
                vioList.innerHTML = `<div style="grid-column: 1/-1; color:var(--text-dim); text-align:center; padding: 20px;">Không có vi phạm an toàn PPE nào!</div>`;
            } else {
                vioList.innerHTML = data.violation_logs.map(v => `
                    <div class="gallery-item" onclick="viewImageModal('/media/${v.evidence_image}', '${escapeHtml(data.name)} - ${v.time}')">
                        <img src="/media/${v.evidence_image}" alt="Evidence" onerror="this.src='/static/img/avatar_default.png'">
                        <small style="color:var(--danger); font-weight:700;">${escapeHtml(v.violation)}</small>
                        <small>${v.time}</small>
                    </div>
                `).join('');
            }

            openModal('modal-emp-detail');
        }
    } catch (e) {
        showToast('Lỗi tải chi tiết nhân viên', 'error');
    }
}

function openEditEmployee(name, role) {
    document.getElementById('edit-emp-original-name').value = name;
    document.getElementById('edit-emp-name').value = name;
    document.getElementById('edit-emp-role').value = role;
    document.getElementById('edit-emp-file').value = '';
    openModal('modal-edit-employee');
}

async function deleteEmployee(name) {
    if (!confirm(`Bạn có chắc chắn muốn xóa nhân viên "${name}" khỏi hệ thống?`)) return;
    try {
        const res = await fetch(`/api/employees/${encodeURIComponent(name)}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            loadEmployees();
            fetchRealtimeStats();
        } else {
            showToast(data.message, 'error');
        }
    } catch (e) {
        showToast('Không thể kết nối máy chủ', 'error');
    }
}

// =========================================================
// STRANGERS HUB
// =========================================================
function initStrangersHub() {
    document.getElementById('btn-clear-all-strangers').addEventListener('click', async () => {
        if (!confirm('Bạn có chắc chắn muốn xóa tất cả hồ sơ và ảnh đối tượng người lạ?')) return;
        try {
            const res = await fetch('/api/strangers', { method: 'DELETE' });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(data.message, 'success');
                loadStrangers();
                fetchRealtimeStats();
            }
        } catch (e) {
            showToast('Lỗi khi dọn dẹp ảnh người lạ', 'error');
        }
    });

    document.getElementById('btn-submit-convert').addEventListener('click', async () => {
        const id = document.getElementById('convert-stranger-id').value;
        const name = document.getElementById('convert-emp-name').value.trim();
        const role = document.getElementById('convert-emp-role').value;

        if (!name) {
            showToast('Vui lòng nhập tên cho nhân viên mới!', 'error');
            return;
        }

        try {
            const res = await fetch(`/api/strangers/${id}/convert`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, role })
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(data.message, 'success');
                closeModal('modal-convert-stranger');
                loadStrangers();
                loadEmployees();
                fetchRealtimeStats();
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            showToast('Không thể chuyển đổi người lạ', 'error');
        }
    });
}

async function loadStrangers() {
    try {
        const res = await fetch('/api/strangers');
        const data = await res.json();
        if (data.status === 'success') {
            cachedStrangers = data.data;
            renderStrangers(cachedStrangers);
        }
    } catch (e) {
        console.error('Lỗi nạp người lạ:', e);
    }
}

function renderStrangers(list) {
    const container = document.getElementById('strangers-grid-container');
    if (!container) return;

    if (list.length === 0) {
        container.innerHTML = `<div class="empty-state" style="grid-column: 1/-1; padding: 40px; text-align: center; color: var(--text-dim);">Không có người lạ nào được phát hiện. Khu vực an ninh an toàn!</div>`;
        return;
    }

    container.innerHTML = list.map(st => {
        const imgSrc = st.image_path ? `/media/${st.image_path}` : '/static/img/avatar_default.png';
        return `
            <div class="stranger-card">
                <div class="stranger-img-wrapper" onclick="viewImageModal('${imgSrc}', 'Người lạ ghi nhận lúc ${st.time}')">
                    <img src="${imgSrc}" class="stranger-img" alt="Stranger" onerror="this.src='/static/img/avatar_default.png'">
                    <span class="badge-stranger-tag">NGƯỜI LẠ</span>
                </div>
                <div class="stranger-meta">
                    <span class="stranger-time"><i class="fa-regular fa-clock"></i> ${st.time}</span>
                    <span class="stranger-loc"><i class="fa-solid fa-location-dot"></i> ${escapeHtml(st.location)}</span>
                    <span class="stranger-ppe"><i class="fa-solid fa-shield"></i> ${escapeHtml(st.ppe_status || 'Chưa kiểm tra')}</span>

                    <div class="stranger-btn-row">
                        <button class="btn-convert-st" onclick="openConvertStranger(${st.id}, '${imgSrc}', '${st.time}')">
                            <i class="fa-solid fa-user-plus"></i> Đăng Ký Nhân Viên
                        </button>
                        <button class="btn-del-st" onclick="deleteStranger(${st.id})">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function openConvertStranger(id, imgSrc, time) {
    document.getElementById('convert-stranger-id').value = id;
    document.getElementById('convert-stranger-img').src = imgSrc;
    document.getElementById('convert-stranger-time').textContent = `Thời gian chụp: ${time}`;
    document.getElementById('convert-emp-name').value = '';
    openModal('modal-convert-stranger');
}

async function deleteStranger(id) {
    if (!confirm('Xóa đối tượng người lạ này?')) return;
    try {
        const res = await fetch(`/api/strangers/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            loadStrangers();
            fetchRealtimeStats();
        }
    } catch (e) {
        showToast('Lỗi khi xóa', 'error');
    }
}

// =========================================================
// VIOLATIONS HUB
// =========================================================
function initViolationsHub() {
    const filterInput = document.getElementById('input-filter-vio');
    filterInput.addEventListener('input', () => {
        const q = filterInput.value.toLowerCase().trim();
        const filtered = cachedViolations.filter(v =>
            v.name.toLowerCase().includes(q) || v.violation.toLowerCase().includes(q)
        );
        renderViolationsTable(filtered);
    });
}

async function loadViolations() {
    try {
        const res = await fetch('/api/violations');
        const data = await res.json();
        if (data.status === 'success') {
            cachedViolations = data.data;
            renderViolationsTable(cachedViolations);
        }
    } catch (e) {
        console.error('Lỗi nạp vi phạm:', e);
    }
}

function renderViolationsTable(list) {
    const tbody = document.getElementById('violations-tbody');
    if (!tbody) return;

    if (list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-dim); padding: 30px;">Không có vi phạm an toàn nào được ghi nhận.</td></tr>`;
        return;
    }

    tbody.innerHTML = list.map(v => {
        const imgSrc = v.evidence_image ? `/media/${v.evidence_image}` : '/static/img/avatar_default.png';
        return `
            <tr>
                <td>
                    <img src="${imgSrc}" class="table-evidence-thumb" alt="Evidence" onclick="viewImageModal('${imgSrc}', '${escapeHtml(v.name)} - ${v.time}')" onerror="this.src='/static/img/avatar_default.png'">
                </td>
                <td><strong style="color:#ffffff;">${escapeHtml(v.name)}</strong></td>
                <td>
                    <span class="table-viol-tag">${escapeHtml(v.violation)}</span>
                </td>
                <td style="font-family: var(--font-mono); color: var(--text-muted);">${v.time}</td>
                <td>
                    <button class="btn btn-outline" style="padding: 4px 10px; font-size: 11px;" onclick="viewImageModal('${imgSrc}', '${escapeHtml(v.name)} - ${v.time}')">
                        <i class="fa-solid fa-expand"></i> Xem Bằng Chứng
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// =========================================================
// SETTINGS & ZALO
// =========================================================
function initSettingsHub() {
    // Lưu toàn bộ cấu hình (Zalo + Cảnh báo người lạ + Tiếng bíp)
    document.getElementById('btn-save-settings').addEventListener('click', async () => {
        const zEnabled = document.getElementById('chk-zalo-enabled').checked;
        const zWebhook = document.getElementById('inp-zalo-webhook').value.trim();
        const zToken = document.getElementById('inp-zalo-token').value.trim();
        const zUserId = document.getElementById('inp-zalo-userid').value.trim();
        const zCooldown = parseInt(document.getElementById('inp-zalo-cooldown').value) || 45;

        const chkStrangerEl = document.getElementById('chk-stranger-voice-enabled') || document.getElementById('chk-voice-enabled');
        const vEnabled = chkStrangerEl ? chkStrangerEl.checked : true;
        const chkBeepEl = document.getElementById('chk-beep-enabled');
        const beepEnabled = chkBeepEl ? chkBeepEl.checked : false;

        const vInterval = parseInt(document.getElementById('inp-voice-interval').value) || 30;
        const vType = document.getElementById('sel-voice-type').value;

        try {
            // Lấy cấu hình hiện tại trước khi merge
            const curRes = await fetch('/api/settings');
            const curSettings = await curRes.json();

            curSettings.beep_enabled = beepEnabled;

            curSettings.zalo = {
                enabled: zEnabled,
                webhook_url: zWebhook,
                oa_access_token: zToken,
                oa_user_id: zUserId,
                cooldown_seconds: zCooldown
            };

            curSettings.voice = {
                enabled: vEnabled,
                stranger_enabled: vEnabled,
                interval_seconds: vInterval,
                voice_type: vType
            };

            const saveRes = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(curSettings)
            });
            const data = await saveRes.json();
            if (data.status === 'success') {
                updateVoiceBtnUI(vEnabled);
                showToast('Đã lưu cấu hình Cảnh Báo An Ninh, Tiếng Bíp & Zalo thành công!', 'success');
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            showToast('Lỗi lưu cài đặt', 'error');
        }
    });

    // Test Zalo
    document.getElementById('btn-test-zalo').addEventListener('click', async () => {
        showToast('Đang gửi tin nhắn thử nghiệm tới Zalo...', 'info');
        try {
            const res = await fetch('/api/zalo/test', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                showToast('Đã gửi thông báo kiểm tra tới Zalo!', 'success');
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            showToast('Không thể gửi tin nhắn thử nghiệm Zalo', 'error');
        }
    });

    // Test Giọng Nói Cảnh Báo
    const btnTestVoice = document.getElementById('btn-test-voice');
    if (btnTestVoice) {
        btnTestVoice.addEventListener('click', async () => {
            showToast('Đang yêu cầu hệ thống đọc cảnh báo thử nghiệm...', 'info');
            try {
                const res = await fetch('/api/voice/test', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(data.message, 'success');
                } else {
                    showToast(data.message || 'Hệ thống đang bận', 'error');
                }
            } catch (e) {
                showToast('Không thể kết nối đến máy chủ để thử giọng nói', 'error');
            }
        });
    }

    // Toggle nhanh Voice Alert trong tab Cài đặt
    const btnQuickVoice = document.getElementById('btn-toggle-voice-quick');
    if (btnQuickVoice) {
        btnQuickVoice.addEventListener('click', toggleVoiceAlert);
    }

    // Toggle nhanh Voice Alert trên Header
    const btnHeaderVoice = document.getElementById('btn-web-voice-toggle');
    if (btnHeaderVoice) {
        btnHeaderVoice.addEventListener('click', toggleVoiceAlert);
    }
}

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();

        // Zalo settings
        const z = settings.zalo || {};
        document.getElementById('chk-zalo-enabled').checked = z.enabled !== false;
        document.getElementById('inp-zalo-webhook').value = z.webhook_url || '';
        document.getElementById('inp-zalo-token').value = z.oa_access_token || '';
        document.getElementById('inp-zalo-userid').value = z.oa_user_id || '';
        document.getElementById('inp-zalo-cooldown').value = z.cooldown_seconds || 45;

        // Beep settings
        const chkBeep = document.getElementById('chk-beep-enabled');
        if (chkBeep) chkBeep.checked = settings.beep_enabled === true;

        // Voice & Stranger alert settings
        const v = settings.voice || {};
        const vEnabled = (v.stranger_enabled !== undefined ? v.stranger_enabled : v.enabled) !== false;
        const chkVoice = document.getElementById('chk-stranger-voice-enabled') || document.getElementById('chk-voice-enabled');
        if (chkVoice) chkVoice.checked = vEnabled;

        const inpInterval = document.getElementById('inp-voice-interval');
        if (inpInterval) inpInterval.value = v.interval_seconds || 30;

        const selVoice = document.getElementById('sel-voice-type');
        if (selVoice && v.voice_type) selVoice.value = v.voice_type;

        updateVoiceBtnUI(vEnabled);
    } catch (e) {
        console.error('Lỗi tải settings:', e);
    }
}

async function loadInitialVoiceState() {
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();
        const v = settings.voice || {};
        updateVoiceBtnUI(v.enabled !== false);
    } catch (e) {
        updateVoiceBtnUI(true);
    }
}

function updateVoiceBtnUI(enabled) {
    const btn = document.getElementById('btn-web-voice-toggle');
    if (!btn) return;

    if (enabled) {
        btn.classList.remove('muted');
        btn.innerHTML = `<i class="fa-solid fa-volume-high"></i> <span id="txt-web-voice">Giọng Nói: BẬT</span>`;
    } else {
        btn.classList.add('muted');
        btn.innerHTML = `<i class="fa-solid fa-volume-xmark"></i> <span id="txt-web-voice">Giọng Nói: TẮT</span>`;
    }

    const chk = document.getElementById('chk-voice-enabled');
    if (chk) chk.checked = enabled;
}

async function toggleVoiceAlert() {
    try {
        const res = await fetch('/api/voice/toggle', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            updateVoiceBtnUI(data.enabled);
            showToast(data.message, data.enabled ? 'success' : 'info');
        } else {
            showToast(data.message || 'Lỗi thao tác giọng nói', 'error');
        }
    } catch (e) {
        showToast('Không thể kết nối đến máy chủ để bật/tắt giọng nói', 'error');
    }
}

// =========================================================
// CAMERA ZOOM (CLICK ĐỂ PHÓNG TO, DOUBLE-CLICK ĐỂ THOÁT)
// =========================================================
function openCamZoom(camId, titleText) {
    const modal = document.getElementById('modal-cam-zoom');
    const titleEl = document.getElementById('cam-zoom-title-text');
    const imgEl = document.getElementById('cam-zoom-img');
    if (!modal || !imgEl) return;

    if (titleEl) {
        titleEl.textContent = titleText || (camId === 'cam1' ? 'CAMERA 1: CỔNG KIỂM SOÁT' : 'CAMERA 2: TAPO C200 TOÀN CẢNH');
    }
    // Gán src stream với timestamp để kết nối luồng trực tiếp ngay
    imgEl.src = `/stream/${camId}?t=${Date.now()}`;
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeCamZoom() {
    const modal = document.getElementById('modal-cam-zoom');
    const imgEl = document.getElementById('cam-zoom-img');
    if (modal && modal.classList.contains('active')) {
        modal.classList.remove('active');
    }
    if (imgEl) {
        // Hủy gán src để ngắt kết nối MJPEG stream phóng to, giải phóng CPU & băng thông
        imgEl.src = '';
    }
    document.body.style.overflow = '';
}

// Đăng ký toàn cục để các thẻ HTML gọi được qua inline onclick / ondblclick
window.openCamZoom = openCamZoom;
window.closeCamZoom = closeCamZoom;

function initCamZoomEvents() {
    const modal = document.getElementById('modal-cam-zoom');
    if (modal) {
        modal.addEventListener('dblclick', () => {
            closeCamZoom();
        });
    }

    const imgEl = document.getElementById('cam-zoom-img');
    if (imgEl) {
        imgEl.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            closeCamZoom();
        });
    }
}

// =========================================================
// MODALS & TOAST UTILITIES
// =========================================================
function initModals() {
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
            closeCamZoom();
        }
    });
}

function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.add('active');
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
}

function switchSubTab(subTabId) {
    document.querySelectorAll('.sub-tab-btn').forEach((btn, idx) => {
        btn.classList.toggle('active', (subTabId === 'sub-tab-att' && idx === 0) || (subTabId === 'sub-tab-vio' && idx === 1));
    });
    document.querySelectorAll('.sub-tab-content').forEach(c => {
        c.classList.toggle('active', c.id === subTabId);
    });
}

function viewImageModal(src, caption) {
    document.getElementById('viewer-full-image').src = src;
    document.getElementById('viewer-caption').textContent = caption || '';
    openModal('modal-image-viewer');
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const iconMap = {
        success: 'fa-circle-check',
        error: 'fa-circle-xmark',
        info: 'fa-circle-info'
    };

    toast.innerHTML = `
        <i class="fa-solid ${iconMap[type] || 'fa-bell'}"></i>
        <span>${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(30px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
}
