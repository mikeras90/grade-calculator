// Get references to all the HTML elements
const rosterFileInput = document.getElementById('rosterFile');
const transcriptFileInput = document.getElementById('transcriptFile');
const processButton = document.getElementById('processButton');
const logContainer = document.getElementById('log-container');
const logElement = document.getElementById('log');
const downloadLinksElement = document.getElementById('download-links');
const reconciliationContainer = document.getElementById('reconciliation-container');
const reconciliationForm = document.getElementById('reconciliation-form');
const finalizeButton = document.getElementById('finalizeButton');
const hasHeaderCheckbox = document.getElementById('hasHeader');

// Global variables to store file content and names
let transcriptTextContent = '';
let rosterNames = [];
let nameMap = new Map();
let isNewRoster = false; // --- NEW: Flag to track if we're creating a new key file ---

// Helper function to read a file as text using Promises
function readFileAsText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsText(file);
    });
}

// Function to enable the button only when both files are selected
function checkFiles() {
    processButton.disabled = !(rosterFileInput.files.length > 0 && transcriptFileInput.files.length > 0);
}

// Main function to start the process
async function startProcess() {
    logContainer.style.display = 'block';
    logElement.textContent = 'Starting process...\n';
    reconciliationContainer.style.display = 'none';
    reconciliationForm.innerHTML = '';
    downloadLinksElement.innerHTML = '';

    try {
        const rosterOrKeyFileText = await readFileAsText(rosterFileInput.files[0]);
        transcriptTextContent = await readFileAsText(transcriptFileInput.files[0]);

        const firstLine = rosterOrKeyFileText.split('\n')[0].trim();
        if (firstLine.includes(',') && firstLine.startsWith('Student-')) {
            // --- IT'S A KEY FILE ---
            isNewRoster = false; // Set flag to false
            logElement.textContent += '--> Saved Key File detected. Loading existing pseudonyms...\n';
            nameMap = new Map();
            const keyFileLines = rosterOrKeyFileText.split('\n').filter(line => line.trim() !== '');
            keyFileLines.forEach(line => {
                const [pseudonym, name] = line.split(',');
                if (pseudonym && name) {
                    nameMap.set(name.trim(), pseudonym.trim());
                }
            });
            rosterNames = Array.from(nameMap.keys());

        } else {
            // --- IT'S A NEW ROSTER ---
            isNewRoster = true; // Set flag to true
            logElement.textContent += '--> New Roster detected. Generating new pseudonyms...\n';
            nameMap = new Map();
            let rosterLines = rosterOrKeyFileText.split('\n').filter(line => line.trim() !== '');
            if (hasHeaderCheckbox.checked) {
                rosterLines.shift();
            }
            rosterLines.forEach((line, index) => {
                const name = line.split(',')[0].trim();
                if (name) {
                    const pseudonym = `Student-${index + 1}`;
                    nameMap.set(name, pseudonym);
                }
            });
            rosterNames = Array.from(nameMap.keys());
        }
        logElement.textContent += `    Loaded ${rosterNames.length} students.\n`;

        const transcriptSpeakers = new Set();
        transcriptTextContent.split('\n').forEach(line => {
            if (line.includes(':') && !line.includes('-->')) {
                const speaker = line.split(':')[0].trim();
                transcriptSpeakers.add(speaker);
            }
        });

        const unresolvedNames = [...transcriptSpeakers].filter(speaker => !nameMap.has(speaker) && speaker !== "PROFESSOR");
        logElement.textContent += `    Found ${unresolvedNames.length} unresolved names.\n`;
        
        if (unresolvedNames.length > 0) {
            logElement.textContent += '--> Action required: Please reconcile names below.\n';
            buildReconciliationForm(unresolvedNames);
        } else {
            logElement.textContent += '--> All names resolved. Finalizing now...\n';
            finalizeProcess();
        }
    } catch (error) {
        logElement.textContent += `\nERROR: ${error.message}`;
    }
}

async function finalizeProcess() {
    logElement.textContent += '--> Finalizing anonymization...\n';
    
    const selectElements = reconciliationForm.querySelectorAll('select');
    selectElements.forEach(select => {
        const unresolvedName = select.dataset.unresolvedName;
        const mappedName = select.value;
        if (mappedName !== 'IGNORE' && mappedName !== 'PROFESSOR' && !nameMap.has(unresolvedName)) {
            const pseudonym = nameMap.get(mappedName);
            if (pseudonym) {
                nameMap.set(unresolvedName, pseudonym);
            }
        } else if (mappedName === 'PROFESSOR' && !nameMap.has(unresolvedName)) {
            nameMap.set(unresolvedName, 'PROFESSOR');
        }
    });

    const transcriptLines = transcriptTextContent.split('\n');
    const processedLines = [];
    for (const line of transcriptLines) {
        if (line.includes(':') && !line.includes('-->')) {
            let [speaker, ...speech] = line.split(':');
            speaker = speaker.trim();
            const pseudonym = nameMap.get(speaker) || speaker;
            processedLines.push(pseudonym + ':');
        } else {
            processedLines.push(line);
        }
    }
    const newTranscriptContent = processedLines.join('\n');

    logElement.textContent += '--> Generating download files...\n';
    
    // --- UPDATED DOWNLOAD LOGIC ---
    // Only download the key file if it's a new roster
    if (isNewRoster) {
        const keyFileContent = [];
        const uniquePseudonyms = new Map();
        nameMap.forEach((pseudonym, name) => {
            if (pseudonym.startsWith('Student-')) {
                uniquePseudonyms.set(pseudonym, name);
            }
        });
        uniquePseudonyms.forEach((name, pseudonym) => {
            keyFileContent.push(`${pseudonym},${name}`);
        });
        triggerDownload(keyFileContent.join('\n'), 'anonymized_key.csv', 'text/csv');
    }
    
    // Always download the anonymized transcript
    triggerDownload(newTranscriptContent, 'anonymized_transcript.txt', 'text/plain');

    logElement.textContent += '\nPROCESS COMPLETE!';
    if (isNewRoster) {
        logElement.textContent += '\nKey file and transcript downloaded. REMEMBER TO SAVE YOUR KEY FILE!';
    } else {
        logElement.textContent += '\nAnonymized transcript downloaded.';
    }
    reconciliationContainer.style.display = 'none';
    processButton.style.display = 'block';
}


// --- Other helper functions (no changes needed) ---
function sanitizeForId(name) { return name.replace(/[^a-zA-Z0-9]/g, '_'); }
function buildReconciliationForm(unresolvedNames) {
    reconciliationContainer.style.display = 'block';
    processButton.style.display = 'none';
    const options = rosterNames.map(name => `<option value="${name}">${name}</option>`).join('');
    unresolvedNames.forEach(name => {
        const safeId = sanitizeForId(name);
        const escapedName = name.replace(/"/g, '&quot;');
        const row = document.createElement('div');
        row.className = 'mapping-row';
        row.innerHTML = `<label for="map_${safeId}">${escapedName}:</label><select id="map_${safeId}" data-unresolved-name="${escapedName}"><option value="IGNORE">Ignore this name</option><option value="PROFESSOR">PROFESSOR</option><option disabled>----------------</option>${options}</select>`;
        reconciliationForm.appendChild(row);
    });
}
function triggerDownload(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.textContent = `Download ${filename}`;
    downloadLinksElement.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
}
// Attach event listeners
rosterFileInput.addEventListener('change', checkFiles);
transcriptFileInput.addEventListener('change', checkFiles);
processButton.addEventListener('click', startProcess);
finalizeButton.addEventListener('click', finalizeProcess);