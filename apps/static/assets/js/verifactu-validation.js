/**
 * Funciones de validación VERI*FACTU según normativa de la Agencia Tributaria Española
 * Implementa las validaciones requeridas para el sistema de verificación de facturas
 */

// Configuración de la API de VERI*FACTU (URLs oficiales de la AEAT)
const VERIFACTU_CONFIG = {
    AEAT_VALIDATION_URL: 'https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR',
    AEAT_API_URL: 'https://prewww2.aeat.es/wlpl/TIKE-CONT/ws/FacturaE',
    HASH_ALGORITHM: 'SHA-256',
    QR_VALIDATION_PATTERN: /^https:\/\/prewww2\.aeat\.es\/wlpl\/TIKE-CONT\/ValidarQR\?/,
    SIF_PATTERN: /^[A-Z0-9]{8,20}$/,
    HASH_PATTERN: /^[A-Fa-f0-9]{64}$/
};

/**
 * Función principal para validar la factura según VERI*FACTU
 * Realiza validaciones de integridad, formato y consistencia de datos
 */
async function chkVeriFactu() {
    try {
        // Mostrar indicador de carga
        showValidationLoader('Validando factura VERI*FACTU...');
        
        // Obtener datos de la factura desde el DOM
        const facturaData = extractFacturaData();
        
        if (!facturaData) {
            throw new Error('No se pudieron extraer los datos de la factura');
        }

        // Realizar validaciones paso a paso
        const validationResults = {
            formatValidation: await validateDataFormat(facturaData),
            hashValidation: await validateHashIntegrity(facturaData),
            chainValidation: await validateBlockchain(facturaData),
            sifValidation: await validateSifIdentifier(facturaData),
            aeateValidation: await validateWithAEAT(facturaData)
        };

        // Procesar resultados de validación
        const overallResult = processValidationResults(validationResults);
        
        // Mostrar resultados al usuario
        displayValidationResults(overallResult, validationResults);
        
        return overallResult;

    } catch (error) {
        console.error('Error en validación VERI*FACTU:', error);
        showValidationError('Error al validar la factura: ' + error.message);
        return false;
    } finally {
        hideValidationLoader();
    }
}

/**
 * Función para validar el código QR según normativa VERI*FACTU
 * Verifica la estructura, contenido y autenticidad del código QR
 */
async function chkQRcode() {
    try {
        // Mostrar indicador de carga
        showValidationLoader('Validando código QR VERI*FACTU...');
        
        // Obtener la imagen del código QR
        const qrImage = document.querySelector('.qr-code');
        if (!qrImage) {
            throw new Error('No se encontró el código QR en la factura');
        }

        // Extraer datos del QR (simulación - en producción usarías una librería de QR)
        const qrData = await extractQRData(qrImage);
        
        if (!qrData) {
            throw new Error('No se pudo leer el contenido del código QR');
        }

        // Validar estructura del QR según normativa
        const qrValidation = {
            formatValidation: validateQRFormat(qrData),
            urlValidation: validateQRUrl(qrData),
            dataConsistency: await validateQRDataConsistency(qrData),
            aeateValidation: await validateQRWithAEAT(qrData)
        };

        // Procesar resultados
        const qrResult = processQRValidationResults(qrValidation);
        
        // Mostrar resultados
        displayQRValidationResults(qrResult, qrValidation);
        
        // Mostrar modal con QR ampliado si la validación es exitosa
        if (qrResult.isValid) {
            showQRModal();
        }
        
        return qrResult;

    } catch (error) {
        console.error('Error en validación de QR:', error);
        showValidationError('Error al validar el código QR: ' + error.message);
        return false;
    } finally {
        hideValidationLoader();
    }
}

/**
 * Extrae los datos de la factura desde el DOM
 */
function extractFacturaData() {
    try {
        const facturaData = {
            numero: document.querySelector('.factura-numero')?.textContent?.replace('Nº ', '').trim(),
            hash: document.querySelector('.verifactur-value')?.textContent?.split(' ')[0]?.trim(),
            previousHash: document.querySelectorAll('.verifactur-value')[1]?.textContent?.split(' ')[0]?.trim(),
            sifIdentifier: document.querySelectorAll('.verifactur-value')[2]?.textContent?.split(' ')[0]?.trim(),
            emisor: {
                nombre: document.querySelector('.info-section:first-child .info-value')?.textContent?.trim(),
                dni: document.querySelectorAll('.info-section:first-child .info-value')[1]?.textContent?.trim(),
                email: document.querySelectorAll('.info-section:first-child .info-value')[2]?.textContent?.trim()
            },
            receptor: {
                sociedad: document.querySelector('.info-section:last-child .info-value')?.textContent?.trim(),
                cif: document.querySelectorAll('.info-section:last-child .info-value')[2]?.textContent?.trim()
            },
            importes: {
                base: document.querySelectorAll('.importe-item span')[3]?.textContent?.replace(' €', '').trim(),
                total: document.querySelector('.importe-item.total span:last-child')?.textContent?.replace(' €', '').trim()
            },
            fecha: new Date().toISOString().split('T')[0]
        };

        return facturaData;
    } catch (error) {
        console.error('Error extrayendo datos de factura:', error);
        return null;
    }
}

/**
 * Valida el formato de los datos de la factura
 */
async function validateDataFormat(data) {
    const validations = {
        numeroFactura: data.numero && data.numero.length > 0,
        hashFormat: VERIFACTU_CONFIG.HASH_PATTERN.test(data.hash),
        previousHashFormat: !data.previousHash || VERIFACTU_CONFIG.HASH_PATTERN.test(data.previousHash),
        sifFormat: VERIFACTU_CONFIG.SIF_PATTERN.test(data.sifIdentifier),
        emisorData: data.emisor.nombre && data.emisor.dni,
        receptorData: data.receptor.sociedad && data.receptor.cif,
        importesData: data.importes.base && data.importes.total
    };

    return {
        isValid: Object.values(validations).every(v => v),
        details: validations
    };
}

/**
 * Valida la integridad del hash de verificación
 */
async function validateHashIntegrity(data) {
    try {
        // Construir cadena de datos para hash según normativa VERI*FACTU
        const dataString = [
            data.numero,
            data.emisor.dni,
            data.receptor.cif,
            data.importes.total,
            data.fecha,
            data.sifIdentifier
        ].join('|');

        // Calcular hash esperado (simulación - en producción usarías crypto real)
        const expectedHash = await calculateSHA256(dataString);
        
        return {
            isValid: data.hash === expectedHash,
            expectedHash: expectedHash,
            actualHash: data.hash,
            dataString: dataString
        };
    } catch (error) {
        return {
            isValid: false,
            error: error.message
        };
    }
}

/**
 * Valida la cadena de bloques (blockchain) de VERI*FACTU
 */
async function validateBlockchain(data) {
    try {
        // En un sistema real, esto consultaría la base de datos de facturas anteriores
        // Por ahora, validamos que el hash anterior tenga el formato correcto
        const isValidChain = !data.previousHash || 
                           (VERIFACTU_CONFIG.HASH_PATTERN.test(data.previousHash) && 
                            data.previousHash !== data.hash);

        return {
            isValid: isValidChain,
            previousHash: data.previousHash,
            currentHash: data.hash
        };
    } catch (error) {
        return {
            isValid: false,
            error: error.message
        };
    }
}

/**
 * Valida el identificador SIF
 */
async function validateSifIdentifier(data) {
    return {
        isValid: VERIFACTU_CONFIG.SIF_PATTERN.test(data.sifIdentifier),
        sifIdentifier: data.sifIdentifier,
        format: 'Debe ser alfanumérico de 8-20 caracteres'
    };
}

/**
 * Valida con la AEAT (simulación)
 */
async function validateWithAEAT(data) {
    try {
        // En producción, esto haría una llamada real a la API de la AEAT
        // Por ahora, simulamos la validación
        
        const mockResponse = await new Promise(resolve => {
            setTimeout(() => {
                resolve({
                    valid: true,
                    status: 'ACTIVE',
                    timestamp: new Date().toISOString()
                });
            }, 2000);
        });

        return {
            isValid: mockResponse.valid,
            status: mockResponse.status,
            timestamp: mockResponse.timestamp
        };
    } catch (error) {
        return {
            isValid: false,
            error: 'No se pudo conectar con la AEAT'
        };
    }
}

/**
 * Extrae datos del código QR (simulación)
 */
async function extractQRData(qrImage) {
    // En producción, usarías una librería como jsQR o qr-scanner
    // Por ahora, simulamos la extracción de datos
    return {
        url: 'https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR?id=12345&hash=abc123',
        facturaId: '12345',
        hash: 'abc123',
        timestamp: new Date().toISOString()
    };
}

/**
 * Valida el formato del QR según normativa
 */
function validateQRFormat(qrData) {
    return {
        isValid: VERIFACTU_CONFIG.QR_VALIDATION_PATTERN.test(qrData.url),
        url: qrData.url
    };
}

/**
 * Valida la URL del QR
 */
function validateQRUrl(qrData) {
    try {
        const url = new URL(qrData.url);
        const isValidDomain = url.hostname === 'prewww2.aeat.es';
        const hasRequiredParams = url.searchParams.has('id') && url.searchParams.has('hash');
        
        return {
            isValid: isValidDomain && hasRequiredParams,
            domain: url.hostname,
            params: Object.fromEntries(url.searchParams)
        };
    } catch (error) {
        return {
            isValid: false,
            error: 'URL inválida'
        };
    }
}

/**
 * Valida consistencia de datos del QR con la factura
 */
async function validateQRDataConsistency(qrData) {
    const facturaData = extractFacturaData();
    
    return {
        isValid: qrData.hash === facturaData.hash,
        qrHash: qrData.hash,
        facturaHash: facturaData.hash
    };
}

/**
 * Valida QR con la AEAT
 */
async function validateQRWithAEAT(qrData) {
    try {
        // Simulación de validación con AEAT
        const mockResponse = await new Promise(resolve => {
            setTimeout(() => {
                resolve({
                    valid: true,
                    facturaExists: true,
                    status: 'VERIFIED'
                });
            }, 1500);
        });

        return {
            isValid: mockResponse.valid,
            facturaExists: mockResponse.facturaExists,
            status: mockResponse.status
        };
    } catch (error) {
        return {
            isValid: false,
            error: 'Error al validar con AEAT'
        };
    }
}

/**
 * Procesa los resultados de validación
 */
function processValidationResults(results) {
    const allValid = Object.values(results).every(result => result.isValid);
    
    return {
        isValid: allValid,
        score: calculateValidationScore(results),
        results: results,
        timestamp: new Date().toISOString()
    };
}

/**
 * Procesa los resultados de validación del QR
 */
function processQRValidationResults(results) {
    const allValid = Object.values(results).every(result => result.isValid);
    
    return {
        isValid: allValid,
        results: results,
        timestamp: new Date().toISOString()
    };
}

/**
 * Calcula puntuación de validación
 */
function calculateValidationScore(results) {
    const weights = {
        formatValidation: 20,
        hashValidation: 30,
        chainValidation: 20,
        sifValidation: 15,
        aeateValidation: 15
    };
    
    let score = 0;
    for (const [key, result] of Object.entries(results)) {
        if (result.isValid) {
            score += weights[key] || 0;
        }
    }
    
    return score;
}

/**
 * Muestra los resultados de validación
 */
function displayValidationResults(overallResult, detailedResults) {
    const resultHtml = `
        <div class="validation-results">
            <h3>Resultado de Validación VERI*FACTU</h3>
            <div class="overall-result ${overallResult.isValid ? 'valid' : 'invalid'}">
                <span class="status-icon">${overallResult.isValid ? '✅' : '❌'}</span>
                <span class="status-text">
                    ${overallResult.isValid ? 'FACTURA VÁLIDA' : 'FACTURA INVÁLIDA'}
                </span>
                <span class="score">Puntuación: ${overallResult.score}/100</span>
            </div>
            <div class="detailed-results">
                ${Object.entries(detailedResults).map(([key, result]) => `
                    <div class="result-item ${result.isValid ? 'valid' : 'invalid'}">
                        <span class="result-icon">${result.isValid ? '✅' : '❌'}</span>
                        <span class="result-name">${getValidationName(key)}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    
    showModal('Validación VERI*FACTU', resultHtml);
}

/**
 * Muestra los resultados de validación del QR
 */
function displayQRValidationResults(qrResult, detailedResults) {
    const resultHtml = `
        <div class="qr-validation-results">
            <h3>Resultado de Validación del Código QR</h3>
            <div class="overall-result ${qrResult.isValid ? 'valid' : 'invalid'}">
                <span class="status-icon">${qrResult.isValid ? '✅' : '❌'}</span>
                <span class="status-text">
                    ${qrResult.isValid ? 'CÓDIGO QR VÁLIDO' : 'CÓDIGO QR INVÁLIDO'}
                </span>
            </div>
            <div class="detailed-results">
                ${Object.entries(detailedResults).map(([key, result]) => `
                    <div class="result-item ${result.isValid ? 'valid' : 'invalid'}">
                        <span class="result-icon">${result.isValid ? '✅' : '❌'}</span>
                        <span class="result-name">${getQRValidationName(key)}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    
    showModal('Validación Código QR', resultHtml);
}

/**
 * Funciones auxiliares para UI
 */
function getValidationName(key) {
    const names = {
        formatValidation: 'Formato de Datos',
        hashValidation: 'Integridad del Hash',
        chainValidation: 'Cadena de Bloques',
        sifValidation: 'Identificador SIF',
        aeateValidation: 'Validación AEAT'
    };
    return names[key] || key;
}

function getQRValidationName(key) {
    const names = {
        formatValidation: 'Formato del QR',
        urlValidation: 'URL de Validación',
        dataConsistency: 'Consistencia de Datos',
        aeateValidation: 'Verificación AEAT'
    };
    return names[key] || key;
}

function showValidationLoader(message) {
    const loader = document.createElement('div');
    loader.id = 'validation-loader';
    loader.innerHTML = `
        <div class="loader-overlay">
            <div class="loader-content">
                <div class="spinner"></div>
                <p>${message}</p>
            </div>
        </div>
    `;
    document.body.appendChild(loader);
}

function hideValidationLoader() {
    const loader = document.getElementById('validation-loader');
    if (loader) {
        loader.remove();
    }
}

function showValidationError(message) {
    alert('Error de Validación: ' + message);
}

function showModal(title, content) {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <span class="close" onclick="this.parentElement.parentElement.remove()">&times;</span>
            <h3>${title}</h3>
            ${content}
        </div>
    `;
    document.body.appendChild(modal);
    modal.style.display = 'block';
}

function showQRModal() {
    const modal = document.getElementById('qrModal');
    if (modal) {
        modal.style.display = 'block';
    }
}

function closeQRModal() {
    const modal = document.getElementById('qrModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * Función auxiliar para calcular SHA-256 (simulación)
 */
async function calculateSHA256(data) {
    // En producción, usarías crypto.subtle.digest
    // Por ahora, simulamos un hash
    let hash = 0;
    for (let i = 0; i < data.length; i++) {
        const char = data.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    return Math.abs(hash).toString(16).padStart(64, '0');
}

/**
 * Event listeners para los botones
 */
document.addEventListener('DOMContentLoaded', function() {
    // Botón de validación VERI*FACTU
    document.getElementById('validateBtn').addEventListener('click', function(e) {
        e.preventDefault();
        chkVeriFactu();
    });
    
    // Botón de validación QR
    document.getElementById('qrBtn').addEventListener('click', function(e) {
        e.preventDefault();
        chkQRcode();
    });
});

// Función para copiar al portapapeles (ya existente en el código original)
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Copiado al portapapeles');
    }).catch(err => {
        console.error('Error al copiar: ', err);
    });
}