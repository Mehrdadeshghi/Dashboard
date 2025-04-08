document.addEventListener('DOMContentLoaded', function() {
    const deviceDropdown = document.getElementById('deviceDropdown');
    const ctx = document.getElementById('usageChart').getContext('2d');
    let usageChart;

    function loadSelectedDeviceData() {
        const selectedDeviceMac = deviceDropdown.value;

        // Bewegungsdaten für das ausgewählte Gerät abrufen
        fetch(`/api/motion_chart_data?mac_address=${encodeURIComponent(selectedDeviceMac)}`)
            .then(response => response.json())
            .then(data => {
                updateChart(data);
            })
            .catch(error => console.error('Fehler beim Laden der Bewegungsdaten:', error));
    }

    function updateChart(data) {
        if (usageChart) {
            usageChart.destroy();
        }

        usageChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Anzahl Bewegungen',
                    data: data.values,
                    borderColor: 'rgba(75, 192, 192, 1)',
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Datum'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Anzahl Bewegungen'
                        }
                    }
                }
            }
        });
    }

    // Initiale Daten für das ausgewählte Gerät laden
    loadSelectedDeviceData();
});

