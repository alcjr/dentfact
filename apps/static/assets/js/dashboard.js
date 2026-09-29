document.addEventListener("DOMContentLoaded", async () => {
    await loadFilters();
});

async function loadFilters() {
    const response = await fetch('/api/filters/');
    const data = await response.json();

    populateSelect('ano', data.years);
    populateSelect('mes', data.months);
}

function populateSelect(id, items) {
    const select = document.getElementById(id);
    items.forEach(item => {
        const option = document.createElement('option');
        option.value = item;
        option.textContent = item;
        select.appendChild(option);
    });
}

async function applyFilters() {
    const filters = {
        mes: document.getElementById('mes').value,
        ano: document.getElementById('ano').value,
        spcode: document.getElementById('spcode').value,
        doctor: document.getElementById('doctor').value,
        sociedad: document.getElementById('sociedad').value
    };

    const response = await fetch('/api/data/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken'), // Manejar CSRF en Django
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: new URLSearchParams(filters)
    });

    const data = await response.json();
    updateCharts(data);
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            // Check if this cookie string begins with the name we want
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function updateCharts(data) {
    const ctxBaseImp = document.getElementById('chartBaseImp').getContext('2d');
    const ctxBaseCal = document.getElementById('chartBaseCal').getContext('2d');
    const ctxTotal = document.getElementById('chartTotal').getContext('2d');

    new Chart(ctxBaseImp, {
        type: 'bar',
        data: {
            labels: ['Base Imp.'],
            datasets: [{
                label: 'Base Imp.',
                data: [data.baseImp],
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });

    new Chart(ctxBaseCal, {
        type: 'bar',
        data: {
            labels: ['Base Cal.'],
            datasets: [{
                label: 'Base Cal.',
                data: [data.baseCal],
                backgroundColor: 'rgba(153, 102, 255, 0.2)',
                borderColor: 'rgba(153, 102, 255, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });

    new Chart(ctxTotal, {
        type: 'bar',
        data: {
            labels: ['Total'],
            datasets: [{
                label: 'Total',
                data: [data.total],
                backgroundColor: 'rgba(255, 99, 132, 0.2)',
                borderColor: 'rgba(255, 99, 132, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}
