// Update clock in connection bar
function updateClockText() {
    const n = new Date();
    const t = n.toTimeString().slice(0, 8);
    const el = document.getElementById('clockText');
    if (el) el.textContent = t;
}
setInterval(updateClockText, 1000);
updateClockText();

// DOM Elements
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const messagesArea = document.getElementById('messagesArea');
const voiceBtn = document.getElementById('voiceBtn');
const imageUploadBtn = document.getElementById('imageUploadBtn');
const imageInput = document.getElementById('imageInput');
const fileUploadBtn = document.getElementById('fileUploadBtn');
const fileInput = document.getElementById('fileInput');
const attachmentsPreview = document.getElementById('attachmentsPreview');
const newProjectBtn = document.querySelector('.new-project-btn');
const quickActionCards = document.querySelectorAll('.quick-action-card');
const themeToggleBtn = document.getElementById('themeToggleBtn');

const THEME_KEY = 'nexus_theme';

function applyTheme(theme) {
    const isDark = theme === 'dark';
    document.body.classList.toggle('dark-mode', isDark);
    if (themeToggleBtn) {
        themeToggleBtn.textContent = isDark ? 'Light' : 'Dark';
        themeToggleBtn.setAttribute('aria-pressed', String(isDark));
    }
}

function initTheme() {
    let stored = null;
    try {
        stored = localStorage.getItem(THEME_KEY);
    } catch (_) {
        stored = null;
    }
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    applyTheme(stored === 'dark' || stored === 'light' ? stored : (prefersDark ? 'dark' : 'light'));
}

if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
        const nextTheme = document.body.classList.contains('dark-mode') ? 'light' : 'dark';
        applyTheme(nextTheme);
        try {
            localStorage.setItem(THEME_KEY, nextTheme);
        } catch (_) {
            // No-op
        }
    });
}

// State
// State
let isRecording = false;
let recognition = null;
let attachedFiles = [];
let setupBannerEl = null;
const VOICE_SILENCE_MS = 20000;
let voiceSilenceTimer = null;
let voiceManualStop = false;
let voiceTranscriptBuffer = '';

function clearVoiceSilenceTimer() {
    if (voiceSilenceTimer) {
        clearTimeout(voiceSilenceTimer);
        voiceSilenceTimer = null;
    }
}

function scheduleVoiceAutoSend() {
    clearVoiceSilenceTimer();
    voiceSilenceTimer = setTimeout(() => {
        if (!isRecording) return;
        if (!messageInput.value.trim()) return;
        stopVoiceRecognition(true);
        sendMessage();
    }, VOICE_SILENCE_MS);
}

function stopVoiceRecognition(manual = false) {
    voiceManualStop = manual;
    clearVoiceSilenceTimer();
    if (recognition) {
        try {
            recognition.stop();
        } catch (_) {
            // No-op
        }
    }
    isRecording = false;
    voiceBtn.classList.remove('recording');
}

function ensureSetupBanner() {
    if (setupBannerEl) return setupBannerEl;
    setupBannerEl = document.createElement('div');
    setupBannerEl.id = 'setupBanner';
    setupBannerEl.style.cssText = 'display:none; margin: 10px 0 14px 0; padding: 10px 12px; border-radius: 10px; background: #fff4e5; color: #5d3b00; font-size: 0.88rem;';
    const parent = messagesArea && messagesArea.parentElement ? messagesArea.parentElement : document.body;
    parent.insertBefore(setupBannerEl, messagesArea || parent.firstChild);
    return setupBannerEl;
}

async function checkHealth() {
    try {
        const resp = await fetch('/api/health');
        const data = await resp.json();
        const deps = data.installed_export_deps || {};
        const missing = [];
        if (!deps.python_docx) missing.push('python-docx');
        if (!deps.python_pptx) missing.push('python-pptx');
        if (!deps.openpyxl) missing.push('openpyxl');
        const banner = ensureSetupBanner();
        if (missing.length === 0) {
            banner.style.display = 'none';
            return;
        }
        banner.style.display = 'block';
        banner.innerHTML = `Setup: missing export dependencies (${missing.join(', ')}). Run <code>pip install python-docx python-pptx openpyxl</code>`;
    } catch (e) {
        // Silent fail: health banner is optional.
    }
}

// Auto-resize textarea
messageInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    toggleSendButton();
});

// Toggle send button based on input
function toggleSendButton() {
    const hasContent = messageInput.value.trim() !== '' || attachedFiles.length > 0;
    sendBtn.disabled = !hasContent;
}

// Send message
sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) {
            sendMessage();
        }
    }
});

async function sendMessage() {
    if (isRecording) {
        stopVoiceRecognition(true);
    }

    const text = messageInput.value.trim();

    if (text === '' && attachedFiles.length === 0) return;

    // Hide welcome message if visible
    const welcomeMessage = document.querySelector('.welcome-message');
    if (welcomeMessage) {
        welcomeMessage.style.animation = 'fadeOut 0.3s ease forwards';
        setTimeout(() => welcomeMessage.remove(), 300);
    }

    // Create user message
    const userMessageDiv = createUserMessage(text, attachedFiles);
    messagesArea.appendChild(userMessageDiv);

    // Prepare payload
    const originalText = text;
    const filesToSend = await Promise.all(attachedFiles.map(file => convertToBase64(file)));

    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';
    attachedFiles = [];
    updateAttachmentsPreview();
    toggleSendButton();
    scrollToBottom();

    const typingIndicator = createTypingIndicator();
    messagesArea.appendChild(typingIndicator);
    scrollToBottom();

    // Call Python Backend
    try {
        const response = await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                command: originalText,
                files: filesToSend
            })
        });
        const data = await response.json();
        const aiResponse = data.show_text || data.reply || '';
        const aiSpeakText = data.say_text || aiResponse;
        const aiEvidence = Array.isArray(data.evidence) ? data.evidence : [];
        const aiActions = Array.isArray(data.actions) ? data.actions : [];
        const aiFiles = Array.isArray(data.files) ? data.files : [];
        const aiMeta = data.meta || {};

        typingIndicator.remove();

        const aiMessageDiv = createAIMessage('', aiEvidence, aiActions, aiMeta, aiFiles);
        messagesArea.appendChild(aiMessageDiv);
        const textEl = aiMessageDiv.querySelector('.ai-text');
        await simulateStreamingText(textEl, aiResponse);
        scrollToBottom();

        // Speak response
        speak(aiSpeakText);

    } catch (err) {
        if (typingIndicator && typingIndicator.parentNode) {
            typingIndicator.remove();
        }
        console.error(err);
        const errorDiv = createAIMessage("Error: Could not connect to the Nexus Clinical AI service. Is the engine running?");
        messagesArea.appendChild(errorDiv);
        scrollToBottom();
    }
}

// Helper: Convert file to Base64
function convertToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = () => resolve({
            name: file.name,
            type: file.type,
            content: reader.result.split(',')[1] // Remove 'data:*/*;base64,' prefix
        });
        reader.onerror = error => reject(error);
    });
}

function createUserMessage(text, files) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message user-message';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = 'You';

    const content = document.createElement('div');
    content.className = 'message-content';

    // Add file previews if any
    if (files.length > 0) {
        const filesDiv = document.createElement('div');
        filesDiv.style.marginBottom = '12px';
        files.forEach(file => {
            const fileTag = document.createElement('div');
            fileTag.style.cssText = 'display: inline-block; background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 6px; margin-right: 8px; margin-bottom: 8px; font-size: 0.875rem;';
            fileTag.textContent = file.name;
            filesDiv.appendChild(fileTag);
        });
        content.appendChild(filesDiv);
    }

    if (text) {
        const textP = document.createElement('p');
        textP.textContent = text;
        content.appendChild(textP);
    }

    messageDiv.appendChild(content);
    messageDiv.appendChild(avatar);

    return messageDiv;
}

function createAIMessage(text, evidence = [], actions = [], meta = {}, files = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message ai-message';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = `
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="4" width="7" height="7" fill="currentColor" opacity="0.9"/>
            <rect x="13" y="4" width="7" height="7" fill="currentColor" opacity="0.6"/>
            <rect x="4" y="13" width="7" height="7" fill="currentColor" opacity="0.6"/>
            <rect x="13" y="13" width="7" height="7" fill="currentColor" opacity="0.3"/>
        </svg>
    `;

    const content = document.createElement('div');
    content.className = 'message-content';

    const textP = document.createElement('div');
    textP.className = 'ai-text';
    textP.style.marginBottom = '10px';
    textP.innerHTML = renderSimpleMarkdown(text);
    content.appendChild(textP);

    const translation = (((meta || {}).payload || {}).translation);
    if (translation && typeof translation === 'object') {
        const translationPanel = renderTranslationPanel(translation);
        content.appendChild(translationPanel);
    }

    const insights = (((meta || {}).payload || {}).insights);
    if (insights && typeof insights === 'object') {
        messageDiv.classList.add('insights-message');
        const dashboard = renderInsightsDashboard(insights);
        content.appendChild(dashboard);
    }

    if (evidence.length > 0) {
        const evidenceDiv = renderEvidence(evidence);
        content.appendChild(evidenceDiv);
    }

    if (files.length > 0) {
        const filesDiv = renderFiles(files);
        content.appendChild(filesDiv);
    }

    if (actions.length > 0) {
        const actionDiv = renderActions(actions);
        content.appendChild(actionDiv);
    }

    const detailsDiv = renderDetails(meta);
    if (detailsDiv) {
        content.appendChild(detailsDiv);
    }

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);

    return messageDiv;
}

function renderTranslationPanel(translation) {
    const wrap = document.createElement('div');
    wrap.className = 'translation-panel';
    const language = String(translation.language || 'unknown').toLowerCase();
    const confidence = Math.round((Number(translation.confidence) || 0) * 100);
    const label = language === 'tn' ? 'Setswana' : language === 'en' ? 'English' : 'Unknown';
    const notes = Array.isArray(translation.notes) ? translation.notes : [];
    const keyTerms = Array.isArray(translation.key_terms) ? translation.key_terms : [];
    const original = String(translation.original_transcript || '');
    const normalized = String(translation.normalized_transcript_en || '');

    wrap.innerHTML = `
        <div class="translation-head">
            <strong>Transcript Normalization</strong>
            <span class="translation-badge">${label}</span>
            <span class="translation-confidence">${confidence}% confidence</span>
        </div>
        <div class="translation-line">Language detected: <strong>${label}</strong></div>
    `;

    const details = document.createElement('details');
    details.className = 'translation-details';
    details.innerHTML = `
        <summary>View original transcript</summary>
        <div class="translation-columns">
            <div>
                <div class="translation-col-title">Original</div>
                <pre>${original}</pre>
            </div>
            <div>
                <div class="translation-col-title">Normalized English</div>
                <pre>${normalized}</pre>
            </div>
        </div>
    `;
    wrap.appendChild(details);

    if (keyTerms.length > 0) {
        const terms = document.createElement('div');
        terms.className = 'translation-terms';
        terms.innerHTML = `<div class="translation-col-title">Key terms</div>`;
        const ul = document.createElement('ul');
        keyTerms.slice(0, 20).forEach((item) => {
            const li = document.createElement('li');
            li.textContent = `${item.tn || '-'} -> ${item.en || '-'} (${item.type || 'other'})`;
            ul.appendChild(li);
        });
        terms.appendChild(ul);
        wrap.appendChild(terms);
    }

    if (notes.length > 0) {
        const noteBox = document.createElement('div');
        noteBox.className = 'translation-notes';
        noteBox.innerHTML = `<div class="translation-col-title">Notes</div><ul>${notes.slice(0, 8).map((n) => `<li>${n}</li>`).join('')}</ul>`;
        wrap.appendChild(noteBox);
    }

    return wrap;
}

function _variantClass(variant) {
    const v = String(variant || 'info').toLowerCase();
    if (v === 'danger') return 'var-danger';
    if (v === 'warning') return 'var-warning';
    if (v === 'success') return 'var-success';
    return 'var-info';
}

function _severityVariant(severity) {
    const s = String(severity || '').toLowerCase();
    if (s === 'high') return 'danger';
    if (s === 'medium') return 'warning';
    if (s === 'low') return 'success';
    return 'info';
}

function renderInsightsDashboard(insights) {
    const root = document.createElement('div');
    root.className = 'insights insights-dashboard powerbi';

    const analytics = insights.analytics || {};
    const diagnosis = insights.diagnosis_support || {};
    const actionable = insights.actionable_insights || {};
    const summaryCards = Array.isArray(analytics.summary_cards) ? analytics.summary_cards : [];
    const riskScores = Array.isArray(analytics.risk_scores) ? analytics.risk_scores : [];
    const vitals = Array.isArray(analytics.vitals) ? analytics.vitals : [];
    const gaps = Array.isArray(actionable.documentation_gaps) ? actionable.documentation_gaps : [];
    const redCount = Number(((analytics.red_flag_summary || {}).count) || 0);
    let riskSortDesc = true;
    let activeVitalFilter = 'all';
    const maxRisk = Math.max(...riskScores.map(x => Number(x.value) || 0), 0);
    const gaugePct = Math.round(maxRisk * 100);

    const header = document.createElement('div');
    header.className = 'toolbar insights-toolbar';
    header.innerHTML = `
        <div>
            <div class="insights-title">Clinical Insights Dashboard</div>
            <div class="insights-subtitle">Decision support only; clinician verification required.</div>
        </div>
    `;
    const btnWrap = document.createElement('div');
    btnWrap.className = 'insights-actions';
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'btn insights-btn';
    copyBtn.textContent = 'Copy JSON';
    copyBtn.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(JSON.stringify(insights, null, 2));
            copyBtn.textContent = 'Copied';
            showToast('Insights JSON copied');
            setTimeout(() => { copyBtn.textContent = 'Copy JSON'; }, 1200);
        } catch (e) {
            showToast('Copy failed');
        }
    });
    const exportBtn = document.createElement('button');
    exportBtn.type = 'button';
    exportBtn.className = 'btn insights-btn';
    exportBtn.textContent = 'Export Patient Summary';
    exportBtn.addEventListener('click', () => showToast('Coming soon'));
    const fullscreenBtn = document.createElement('button');
    fullscreenBtn.type = 'button';
    fullscreenBtn.className = 'btn insights-btn';
    fullscreenBtn.textContent = 'Fullscreen';
    fullscreenBtn.addEventListener('click', () => {
        const inFs = root.classList.toggle('insights-fullscreen');
        document.body.classList.toggle('has-insights-fullscreen', inFs);
        fullscreenBtn.textContent = inFs ? 'Exit Fullscreen' : 'Fullscreen';
    });
    btnWrap.appendChild(copyBtn);
    btnWrap.appendChild(exportBtn);
    btnWrap.appendChild(fullscreenBtn);
    header.appendChild(btnWrap);
    root.appendChild(header);

    const controls = document.createElement('div');
    controls.className = 'insights-controls';
    controls.innerHTML = `
        <div class="control-group">
            <span class="control-label">Vitals Filter</span>
            <div class="chip-group" data-role="vital-filter">
                <button class="chip active" data-filter="all">All</button>
                <button class="chip" data-filter="high">High</button>
                <button class="chip" data-filter="low">Low</button>
                <button class="chip" data-filter="normal">Normal</button>
                <button class="chip" data-filter="not_captured">Not captured</button>
            </div>
        </div>
        <div class="control-group control-actions">
            <button type="button" class="btn insights-btn" data-role="sort-risk">Sort Risk: High -> Low</button>
            <button type="button" class="btn insights-btn" data-role="expand-all">Expand All</button>
            <button type="button" class="btn insights-btn" data-role="collapse-all">Collapse All</button>
        </div>
    `;
    root.appendChild(controls);

    const topGrid = document.createElement('div');
    topGrid.className = 'insights-top-grid';

    const cards = document.createElement('div');
    cards.className = 'cards summary-cards';
    summaryCards.forEach((card) => {
        const cardEl = document.createElement('div');
        cardEl.className = `card summary-card ${_variantClass(card.variant)}`;
        const valueRaw = String(card.label || '').toLowerCase().includes('confidence')
            ? `${Math.round((Number(card.value) || 0) * 100)}%`
            : String(card.value ?? '');
        cardEl.innerHTML = `
            <div class="summary-label">${String(card.label || '')}</div>
            <div class="summary-value">${valueRaw}</div>
            <div class="summary-sub">Updated from latest extracted structured data</div>
        `;
        cards.appendChild(cardEl);
    });
    topGrid.appendChild(cards);

    const gaugeWrap = document.createElement('div');
    gaugeWrap.className = 'risk-gauge-card';
    const tier = String(diagnosis.risk_tier || 'low');
    const gaugeClass = tier === 'high' ? 'var-danger' : tier === 'medium' ? 'var-warning' : 'var-success';
    gaugeWrap.innerHTML = `
        <div class="gauge-title">Overall Risk Signal</div>
        <div class="gauge ${gaugeClass}" style="--p:${gaugePct};">
            <div class="gauge-inner">${gaugePct}%</div>
        </div>
        <div class="gauge-meta">
            <span class="badge ${_variantClass(_severityVariant(tier))}">${tier}</span>
            <span class="gauge-red">Red flags: ${redCount}</span>
            <span class="gauge-red">Gaps: ${gaps.length}</span>
        </div>
    `;
    topGrid.appendChild(gaugeWrap);
    root.appendChild(topGrid);

    const middleGrid = document.createElement('div');
    middleGrid.className = 'insights-mid-grid';

    const vitalsBlock = document.createElement('div');
    vitalsBlock.className = 'insights-section visual-card';
    vitalsBlock.innerHTML = `<h4>Vitals Monitor</h4>`;
    const table = document.createElement('table');
    table.className = 'table vitals-table';
    table.innerHTML = '<thead><tr><th>Vital</th><th>Value</th><th>Normal Range</th><th>Status</th><th>Trend</th></tr></thead>';
    const tbody = document.createElement('tbody');
    const renderVitalsRows = () => {
        tbody.innerHTML = '';
        const filtered = vitals.filter((v) => activeVitalFilter === 'all' || String(v.status || 'not_captured') === activeVitalFilter);
        filtered.forEach((v) => {
            const tr = document.createElement('tr');
            const valueNum = Number(v.value);
            const hasNum = !Number.isNaN(valueNum) && v.value !== null && v.value !== undefined;
            const valueText = hasNum ? `${v.value} ${v.unit || ''}`.trim() : 'not captured';
            const min = Number(v.min);
            const max = Number(v.max);
            let pct = 0;
            if (hasNum && !Number.isNaN(min) && !Number.isNaN(max) && max > min) {
                pct = Math.max(0, Math.min(100, ((valueNum - min) / (max - min)) * 100));
            }
            const status = String(v.status || 'not_captured');
            const statusVariant = status === 'normal' ? 'success' : status === 'high' ? 'danger' : status === 'low' ? 'warning' : 'info';
            tr.innerHTML = `
                <td>${v.name || ''}</td>
                <td>${valueText}</td>
                <td>${v.min ?? '-'} - ${v.max ?? '-'}</td>
                <td><span class="pill badge ${_variantClass(statusVariant)}">${status}</span></td>
                <td>
                  <div class="miniTrack">
                    <div class="miniFill ${_variantClass(statusVariant)} animate-fill" style="width:${hasNum ? pct : 0}%"></div>
                  </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
        if (!filtered.length) {
            const emptyRow = document.createElement('tr');
            emptyRow.innerHTML = '<td colspan="5">No vitals match this filter.</td>';
            tbody.appendChild(emptyRow);
        }
    };
    renderVitalsRows();
    table.appendChild(tbody);
    vitalsBlock.appendChild(table);
    middleGrid.appendChild(vitalsBlock);

    const riskBlock = document.createElement('div');
    riskBlock.className = 'insights-section visual-card bars';
    riskBlock.innerHTML = `<h4>Risk Score Distribution</h4>`;
    const renderRiskRows = () => {
        riskBlock.innerHTML = `<h4>Risk Score Distribution</h4>`;
        const sorted = [...riskScores].sort((a, b) => {
            const av = Number(a.value) || 0;
            const bv = Number(b.value) || 0;
            return riskSortDesc ? (bv - av) : (av - bv);
        });
        sorted.forEach((score, idx) => {
            const val = Math.max(0, Math.min(1, Number(score.value) || 0));
            const band = String(score.band || 'low');
            const bVariant = band === 'high' ? 'danger' : band === 'medium' ? 'warning' : 'success';
            const row = document.createElement('details');
            row.className = 'risk-row';
            row.open = idx === 0;
            row.innerHTML = `
                <summary>
                    <span>${score.name || ''}</span>
                    <span class="risk-right">
                        <span class="badge ${_variantClass(bVariant)}">${band}</span>
                        <span>${Math.round(val * 100)}%</span>
                    </span>
                </summary>
                <div class="barTrack risk-bar"><div class="barFill risk-fill ${_variantClass(bVariant)} animate-fill" style="width:${val * 100}%"></div></div>
                <div class="risk-exp">${String(score.explanation || '')}</div>
            `;
            riskBlock.appendChild(row);
        });
    };
    renderRiskRows();
    middleGrid.appendChild(riskBlock);
    root.appendChild(middleGrid);

    const diagDetails = document.createElement('details');
    diagDetails.className = 'insights-details';
    diagDetails.open = true;
    const diffs = Array.isArray(diagnosis.differential_diagnoses) ? diagnosis.differential_diagnoses : [];
    const evidence = Array.isArray(diagnosis.evidence) ? diagnosis.evidence : [];
    const questions = Array.isArray(diagnosis.missing_questions) ? diagnosis.missing_questions : [];
    diagDetails.innerHTML = `<summary>Diagnosis Support</summary>`;
    const diagBody = document.createElement('div');
    diagBody.className = 'insights-detail-body';
    const diffRows = diffs.map((d, i) => `<tr><td>${i + 1}</td><td>${d}</td></tr>`).join('');
    const evRows = evidence.map((e) => `<tr><td>${e.finding || ''}</td><td>${e.source || ''}</td></tr>`).join('');
    diagBody.innerHTML = `
        <div class="detail-grid">
            <div>
                <strong>Differential Diagnoses (possible)</strong>
                <table class="table compact"><thead><tr><th>#</th><th>Condition</th></tr></thead><tbody>${diffRows || '<tr><td colspan="2">No differentials</td></tr>'}</tbody></table>
            </div>
            <div>
                <strong>Evidence Mapping</strong>
                <table class="table compact"><thead><tr><th>Finding</th><th>Source</th></tr></thead><tbody>${evRows || '<tr><td colspan="2">No evidence captured</td></tr>'}</tbody></table>
            </div>
        </div>
        <div><strong>Missing Questions</strong><ul>${questions.map(q => `<li>${q}</li>`).join('')}</ul></div>
    `;
    diagDetails.appendChild(diagBody);
    root.appendChild(diagDetails);

    const actionDetails = document.createElement('details');
    actionDetails.className = 'insights-details';
    actionDetails.open = true;
    actionDetails.innerHTML = `<summary>Actionable Insights</summary>`;
    const actionBody = document.createElement('div');
    actionBody.className = 'insights-detail-body';
    const steps = actionable.recommended_next_steps || {};
    const safety = Array.isArray(actionable.safety_net) ? actionable.safety_net : [];
    actionBody.innerHTML = `
        <div class="step-columns">
            <div class="step-col"><h5>Immediate</h5><ul>${(steps.Immediate || []).map(s => `<li>${s}</li>`).join('')}</ul></div>
            <div class="step-col"><h5>Today</h5><ul>${(steps.Today || []).map(s => `<li>${s}</li>`).join('')}</ul></div>
            <div class="step-col"><h5>Follow-up</h5><ul>${(steps['Follow-up'] || []).map(s => `<li>${s}</li>`).join('')}</ul></div>
        </div>
        <div class="safety-box"><strong>Safety Net</strong><ul>${safety.map(s => `<li>${s}</li>`).join('')}</ul></div>
    `;
    actionDetails.appendChild(actionBody);
    root.appendChild(actionDetails);

    const gapDetails = document.createElement('details');
    gapDetails.className = 'insights-details';
    gapDetails.innerHTML = `<summary>Documentation Gaps</summary>`;
    const gapBody = document.createElement('div');
    gapBody.className = 'insights-detail-body';
    gapBody.innerHTML = `
        <table class="table compact">
            <thead><tr><th>Severity</th><th>Gap</th><th>Why it matters</th></tr></thead>
            <tbody>
                ${(gaps.map(g => `
                    <tr>
                        <td><span class="pill badge ${_variantClass(_severityVariant(g.severity))}">${g.severity || 'info'}</span></td>
                        <td>${g.gap || ''}</td>
                        <td>${g.why_it_matters || ''}</td>
                    </tr>
                `).join('')) || '<tr><td colspan="3">No documentation gaps</td></tr>'}
            </tbody>
        </table>
    `;
    gapDetails.appendChild(gapBody);
    root.appendChild(gapDetails);

    const vitalFilterWrap = controls.querySelector('[data-role="vital-filter"]');
    if (vitalFilterWrap) {
        vitalFilterWrap.querySelectorAll('.chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                activeVitalFilter = chip.getAttribute('data-filter') || 'all';
                vitalFilterWrap.querySelectorAll('.chip').forEach((x) => x.classList.remove('active'));
                chip.classList.add('active');
                renderVitalsRows();
            });
        });
    }

    const sortRiskBtn = controls.querySelector('[data-role="sort-risk"]');
    if (sortRiskBtn) {
        sortRiskBtn.addEventListener('click', () => {
            riskSortDesc = !riskSortDesc;
            sortRiskBtn.textContent = `Sort Risk: ${riskSortDesc ? 'High -> Low' : 'Low -> High'}`;
            renderRiskRows();
        });
    }

    const expandAllBtn = controls.querySelector('[data-role="expand-all"]');
    if (expandAllBtn) {
        expandAllBtn.addEventListener('click', () => {
            root.querySelectorAll('details').forEach((d) => { d.open = true; });
        });
    }

    const collapseAllBtn = controls.querySelector('[data-role="collapse-all"]');
    if (collapseAllBtn) {
        collapseAllBtn.addEventListener('click', () => {
            root.querySelectorAll('details').forEach((d) => { d.open = false; });
        });
    }

    return root;
}

function showToast(text) {
    const toast = document.createElement('div');
    toast.className = 'insights-toast';
    toast.textContent = String(text || 'Done');
    document.body.appendChild(toast);
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 180);
    }, 1200);
}

function renderSimpleMarkdown(text) {
    const escaped = (text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    const linked = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    const bolded = linked.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    return bolded.replace(/\n/g, '<br>');
}

function createTypingIndicator() {
    const wrap = document.createElement('div');
    wrap.className = 'message ai-message';
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = 'AI';

    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerHTML = '<p>Thinking<span class="typing-dots">...</span></p>';

    wrap.appendChild(avatar);
    wrap.appendChild(content);
    return wrap;
}

async function simulateStreamingText(targetEl, fullText) {
    if (!targetEl) return;
    const text = fullText || '';
    if (text.length < 40) {
        targetEl.innerHTML = renderSimpleMarkdown(text);
        return;
    }
    let current = '';
    for (let i = 0; i < text.length; i++) {
        current += text[i];
        if (i % 4 === 0 || i === text.length - 1) {
            targetEl.innerHTML = renderSimpleMarkdown(current);
            await new Promise(resolve => setTimeout(resolve, 8));
        }
    }
}

function attachmentDataUrl(item) {
    if (!item) return '';
    if (item.data) {
        const mime = item.mime_type || item.type || 'image/png';
        return `data:${mime};base64,${item.data}`;
    }
    if (item.url) return item.url;
    if (item.path) return item.path;
    if (item.attachment) {
        const type = item.attachment.type || 'application/octet-stream';
        const content = item.attachment.content || '';
        if (content) return `data:${type};base64,${content}`;
    }
    return '';
}

function renderEvidence(evidence) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-top: 14px; display: grid; gap: 12px;';

    const label = document.createElement('div');
    label.style.cssText = 'font-size:0.85rem; opacity:.8; font-weight:600;';
    label.textContent = `Evidence (${evidence.length})`;
    wrap.appendChild(label);

    const sources = evidence.filter(e => (e.type || '').toLowerCase() === 'link');
    const visuals = evidence.filter(e => (e.type || '').toLowerCase() !== 'link');

    if (sources.length > 0) {
        const sourceSection = document.createElement('details');
        sourceSection.style.cssText = 'background: rgba(0,0,0,0.03); border-radius: 8px; padding: 8px 10px;';

        const sourceSummary = document.createElement('summary');
        sourceSummary.style.cssText = 'cursor: pointer; font-weight:600;';
        sourceSummary.textContent = `Sources (${sources.length})`;
        sourceSection.appendChild(sourceSummary);

        const sourceList = document.createElement('div');
        sourceList.style.cssText = 'display:grid; gap:8px; margin-top:8px;';
        sourceSection.appendChild(sourceList);

        sources.forEach(item => {
            const card = document.createElement('a');
            card.href = item.url || '#';
            card.target = '_blank';
            card.rel = 'noopener noreferrer';
            card.style.cssText = 'display:block; text-decoration:none; background: rgba(0,0,0,0.06); border-radius:8px; padding:10px 12px; color: inherit;';
            const title = document.createElement('div');
            title.textContent = item.title || 'Research Source';
            title.style.cssText = 'font-weight: 600;';
            card.appendChild(title);
            if (item.source || item.caption) {
                const meta = document.createElement('div');
                meta.style.cssText = 'font-size: 0.8rem; opacity: .8; margin-top: 2px;';
                const parts = [];
                if (item.source) parts.push(item.source);
                if (item.caption) parts.push(item.caption);
                meta.textContent = parts.join(' - ');
                card.appendChild(meta);
            }
            sourceList.appendChild(card);
        });

        wrap.appendChild(sourceSection);
    }

    visuals.forEach(item => {
        const type = (item.type || '').toLowerCase();

        if (type === 'image_pair') {
            const card = document.createElement('div');
            card.style.cssText = 'background: rgba(0,0,0,0.04); border-radius: 10px; padding: 10px;';

            const title = document.createElement('div');
            title.style.cssText = 'font-size:0.85rem; margin-bottom:8px; opacity:0.85;';
            title.textContent = item.title || 'Before / After Proof';
            card.appendChild(title);

            const row = document.createElement('div');
            row.style.cssText = 'display:grid; grid-template-columns: 1fr 1fr; gap: 10px;';

            const before = document.createElement('img');
            before.src = attachmentDataUrl(item.before);
            before.alt = 'Before';
            before.style.cssText = 'width:100%; border-radius:8px;';

            const after = document.createElement('img');
            after.src = attachmentDataUrl(item.after);
            after.alt = 'After';
            after.style.cssText = 'width:100%; border-radius:8px;';

            row.appendChild(before);
            row.appendChild(after);
            card.appendChild(row);
            wrap.appendChild(card);
            return;
        }

        if (type === 'image') {
            const card = document.createElement('div');
            card.style.cssText = 'background: rgba(0,0,0,0.04); border-radius: 10px; padding: 10px;';

            if (item.title) {
                const title = document.createElement('div');
                title.style.cssText = 'font-size:0.85rem; margin-bottom:8px; opacity:0.85;';
                title.textContent = item.title;
                card.appendChild(title);
            }

            const img = document.createElement('img');
            img.src = attachmentDataUrl(item);
            img.alt = item.title || 'Evidence image';
            img.style.cssText = 'max-width: 320px; width:100%; border-radius: 8px; display:block;';
            card.appendChild(img);

            if (item.caption) {
                const caption = document.createElement('div');
                caption.style.cssText = 'font-size:0.8rem; margin-top:6px; opacity:.85;';
                caption.textContent = item.caption;
                card.appendChild(caption);
            }
            wrap.appendChild(card);
        }
    });

    return wrap;
}

function renderDetails(meta) {
    if (!meta || Object.keys(meta).length === 0) return null;
    const details = document.createElement('details');
    details.style.cssText = 'margin-top: 10px; background: rgba(0,0,0,0.03); border-radius: 8px; padding: 8px 10px;';

    const summary = document.createElement('summary');
    summary.style.cssText = 'cursor:pointer; font-size: 0.85rem; font-weight:600;';
    summary.textContent = 'Details';
    details.appendChild(summary);

    const body = document.createElement('div');
    body.style.cssText = 'margin-top:8px; font-size: 0.8rem; opacity:.85;';
    const intent = meta.intent ? `Intent: ${meta.intent}` : '';
    const verbosity = meta.verbosity ? `Verbosity: ${meta.verbosity}` : '';
    body.textContent = [intent, verbosity].filter(Boolean).join(' | ');
    details.appendChild(body);
    return details;
}

function renderActions(actions) {
    const box = document.createElement('div');
    box.style.cssText = 'margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px;';

    actions.slice(0, 3).forEach(action => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'quick-action-card';
        btn.style.cssText = 'padding: 8px 10px; border-radius: 8px; border: none; cursor: pointer;';
        btn.textContent = action.label || 'Run';
        btn.addEventListener('click', () => {
            messageInput.value = action.command || '';
            messageInput.dispatchEvent(new Event('input'));
            messageInput.focus();
        });
        box.appendChild(btn);
    });

    return box;
}

function fileIconByType(type) {
    const t = (type || '').toLowerCase();
    if (t === 'docx') return 'DOCX';
    if (t === 'pptx') return 'PPTX';
    if (t === 'xlsx') return 'XLSX';
    if (t === 'pdf') return 'PDF';
    return 'FILE';
}

function renderFiles(files) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-top: 12px; display: grid; gap: 10px;';

    const title = document.createElement('div');
    title.style.cssText = 'font-size:0.85rem; opacity:.8; font-weight:600;';
    title.textContent = `Downloads (${files.length})`;
    wrap.appendChild(title);

    files.forEach(file => {
        const card = document.createElement('div');
        card.style.cssText = 'display:flex; align-items:center; justify-content:space-between; gap:10px; background: rgba(0,0,0,0.04); border-radius: 10px; padding: 10px 12px;';

        const left = document.createElement('div');
        left.style.cssText = 'display:flex; align-items:center; gap:10px; min-width: 0;';

        const icon = document.createElement('div');
        icon.style.cssText = 'font-size:0.75rem; font-weight:700; background:#111; color:#fff; border-radius:6px; padding:4px 6px;';
        icon.textContent = fileIconByType(file.type);

        const info = document.createElement('div');
        info.style.cssText = 'min-width:0;';

        const name = document.createElement('div');
        name.style.cssText = 'font-size:0.9rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:260px;';
        name.textContent = file.name || 'download';

        const meta = document.createElement('div');
        meta.style.cssText = 'font-size:0.78rem; opacity:.75;';
        const sizeKb = file.size ? `${Math.max(1, Math.round(file.size / 1024))} KB` : '';
        meta.textContent = [String(file.type || '').toUpperCase(), sizeKb].filter(Boolean).join(' • ');

        info.appendChild(name);
        info.appendChild(meta);
        left.appendChild(icon);
        left.appendChild(info);

        const btn = document.createElement('a');
        btn.href = file.url || '#';
        btn.textContent = 'Download';
        btn.style.cssText = 'text-decoration:none; font-size:0.82rem; font-weight:600; padding:6px 10px; border-radius:6px; background:#111; color:#fff;';

        card.appendChild(left);
        card.appendChild(btn);
        wrap.appendChild(card);
    });

    return wrap;
}

function generateMockAIResponse(userMessage) {
    // This is a mock response - replace with actual Python backend call
    const responses = [
        "That's a great project idea! Let me help you break it down into manageable phases. First, let's identify the core features and requirements.",
        "I understand. Let's start by creating a project roadmap. What's your target timeline for this project?",
        "Excellent! I can help you structure this project. Let's begin with the planning phase - would you like to define the scope, timeline, or team requirements first?",
        "I'll help you develop a comprehensive project plan. Let's start by identifying your project goals and key deliverables.",
        "Great! Let's organize your project into phases. I can help you with requirements gathering, design, development, and deployment planning."
    ];
    return responses[Math.floor(Math.random() * responses.length)];
}

function scrollToBottom() {
    messagesArea.scrollTop = messagesArea.scrollHeight;
}

// Voice Recording
voiceBtn.addEventListener('click', toggleRecording);

function toggleRecording() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert("Your browser does not support Web Speech API. Please use Chrome or Edge.");
        return;
    }

    if (!isRecording) {
        recognition = new SpeechRecognition();
        recognition.lang = 'en-US';
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;
        voiceManualStop = false;
        voiceTranscriptBuffer = messageInput.value ? `${messageInput.value.trim()} ` : '';

        recognition.onstart = () => {
            isRecording = true;
            voiceBtn.classList.add('recording');
            scheduleVoiceAutoSend();
        };

        recognition.onresult = (event) => {
            let interimText = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const result = event.results[i];
                const transcript = (result[0] && result[0].transcript) ? result[0].transcript.trim() : '';
                if (!transcript) continue;
                if (result.isFinal) {
                    voiceTranscriptBuffer = `${voiceTranscriptBuffer}${transcript} `.replace(/\s+/g, ' ');
                } else {
                    interimText += `${transcript} `;
                }
            }
            messageInput.value = `${voiceTranscriptBuffer}${interimText}`.trim();
            toggleSendButton();
            scheduleVoiceAutoSend();
        };

        recognition.onend = () => {
            if (voiceManualStop) {
                isRecording = false;
                voiceBtn.classList.remove('recording');
                voiceManualStop = false;
                return;
            }
            if (isRecording) {
                try {
                    recognition.start();
                } catch (_) {
                    isRecording = false;
                    voiceBtn.classList.remove('recording');
                }
            }
        };

        recognition.onerror = (event) => {
            console.error('Speech recognition error', event.error);
            isRecording = false;
            voiceBtn.classList.remove('recording');
            clearVoiceSilenceTimer();

            let msg = "Speech recognition error: " + event.error;
            if (event.error === 'not-allowed') {
                msg = "Microphone access denied. Please allow microphone permissions in your browser settings.";
            } else if (event.error === 'service-not-allowed') {
                msg = "Speech service not allowed. Ensure you have internet connection (Chrome uses Google servers).";
            } else if (event.error === 'no-speech') {
                return;
            }
            alert(msg);
        };

        try {
            recognition.start();
            console.log("Recognition started");
        } catch (e) {
            console.error("Start error:", e);
            alert("Could not start recognition: " + e.message);
        }
    } else {
        stopVoiceRecognition(true);
    }
}

// Text to Speech
function speak(text) {
    if ('speechSynthesis' in window) {
        // Cancel any previous speech
        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        // Optional: Select a voice
        // const voices = window.speechSynthesis.getVoices();
        // utterance.voice = voices.find(v => v.lang === 'en-US') || voices[0];

        window.speechSynthesis.speak(utterance);
    }
}

// Image Upload
imageUploadBtn.addEventListener('click', () => imageInput.click());
imageInput.addEventListener('change', handleImageUpload);

function handleImageUpload(e) {
    const files = Array.from(e.target.files);
    files.forEach(file => {
        if (file.type.startsWith('image/')) {
            attachedFiles.push(file);
        }
    });
    updateAttachmentsPreview();
    toggleSendButton();
    imageInput.value = '';
}

// File Upload
fileUploadBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', handleFileUpload);

function handleFileUpload(e) {
    const files = Array.from(e.target.files);
    attachedFiles.push(...files);
    updateAttachmentsPreview();
    toggleSendButton();
    fileInput.value = '';
}

// Update Attachments Preview
function updateAttachmentsPreview() {
    attachmentsPreview.innerHTML = '';

    attachedFiles.forEach((file, index) => {
        const attachmentItem = document.createElement('div');
        attachmentItem.className = 'attachment-item';

        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            attachmentItem.appendChild(img);
        } else {
            const icon = document.createElement('span');
            icon.textContent = '📄';
            attachmentItem.appendChild(icon);
        }

        const fileName = document.createElement('span');
        fileName.textContent = file.name.length > 20 ? file.name.substring(0, 20) + '...' : file.name;
        attachmentItem.appendChild(fileName);

        const removeBtn = document.createElement('span');
        removeBtn.className = 'attachment-remove';
        removeBtn.innerHTML = '✕';
        removeBtn.onclick = () => removeAttachment(index);
        attachmentItem.appendChild(removeBtn);

        attachmentsPreview.appendChild(attachmentItem);
    });
}

function removeAttachment(index) {
    attachedFiles.splice(index, 1);
    updateAttachmentsPreview();
    toggleSendButton();
}

// New Project Button
newProjectBtn.addEventListener('click', () => {
    // Clear messages and show welcome message
    messagesArea.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-icon">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                    <rect x="8" y="8" width="14" height="14" fill="currentColor" opacity="0.9"/>
                    <rect x="26" y="8" width="14" height="14" fill="currentColor" opacity="0.6"/>
                    <rect x="8" y="26" width="14" height="14" fill="currentColor" opacity="0.6"/>
                    <rect x="26" y="26" width="14" height="14" fill="currentColor" opacity="0.3"/>
                </svg>
            </div>
            <h2>Welcome to ProjectForge</h2>
            <p>Share your project idea and I'll help you plan, structure, and bring it to life. Upload images, documents, or use voice to get started.</p>
            
            <div class="quick-actions">
                <button class="quick-action-card">
                    <div class="qa-icon">💡</div>
                    <div class="qa-title">Start from scratch</div>
                    <div class="qa-desc">I have a new project idea</div>
                </button>
                <button class="quick-action-card">
                    <div class="qa-icon">📋</div>
                    <div class="qa-title">Upload documents</div>
                    <div class="qa-desc">I have project requirements</div>
                </button>
                <button class="quick-action-card">
                    <div class="qa-icon">🎯</div>
                    <div class="qa-title">Improve existing</div>
                    <div class="qa-desc">Optimize my current project</div>
                </button>
            </div>
        </div>
    `;

    // Re-attach event listeners to new quick action cards
    attachQuickActionListeners();
});

// Quick Action Cards
function attachQuickActionListeners() {
    const cards = document.querySelectorAll('.quick-action-card');
    cards.forEach(card => {
        card.addEventListener('click', function () {
            const title = this.querySelector('.qa-title').textContent;
            const prompts = {
                'Start from scratch': 'I have a new project idea and need help planning it from the ground up.',
                'Upload documents': 'I have project documentation that I\'d like to discuss and improve.',
                'Improve existing': 'I have an existing project that I want to optimize and enhance.'
            };
            messageInput.value = prompts[title] || '';
            messageInput.focus();
            toggleSendButton();
        });
    });
}

attachQuickActionListeners();

// Project Item Click
document.querySelectorAll('.project-item').forEach(item => {
    item.addEventListener('click', function () {
        document.querySelectorAll('.project-item').forEach(i => i.classList.remove('active'));
        this.classList.add('active');

        // Here you would load the project conversation from your Python backend
        // For now, we'll just clear and show welcome
        const projectName = this.querySelector('.project-name').textContent;
        console.log('Loading project:', projectName);
    });
});

// Auth buttons
const signInBtn = document.querySelector('.signin-btn');
const signUpBtn = document.querySelector('.signup-btn');

if (signInBtn) {
    signInBtn.addEventListener('click', () => {
        // TODO: Implement sign-in functionality
        // This will connect to your Python backend authentication
        console.log('Sign In clicked');
        alert('Sign In functionality will be connected to your Python backend');
    });
}

if (signUpBtn) {
    signUpBtn.addEventListener('click', () => {
        // TODO: Implement sign-up functionality
        // This will connect to your Python backend authentication
        console.log('Sign Up clicked');
        alert('Sign Up functionality will be connected to your Python backend');
    });
}

// Mobile sidebar toggle (optional - add hamburger menu if needed)
const createMobileMenu = () => {
    if (window.innerWidth <= 768) {
        // Add mobile menu functionality here if needed
    }
};

window.addEventListener('resize', createMobileMenu);
createMobileMenu();

// Add fadeOut animation to CSS dynamically
const style = document.createElement('style');
style.textContent = `
    @keyframes fadeOut {
        from { opacity: 1; transform: scale(1); }
        to { opacity: 0; transform: scale(0.95); }
    }
`;
document.head.appendChild(style);


// Right-panel quick commands
document.querySelectorAll('.rp-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const cmd = btn.getAttribute('data-cmd') || btn.textContent.trim();
        messageInput.value = cmd;
        // Trigger input event to resize textarea and enable send button
        messageInput.dispatchEvent(new Event('input'));
        // Optional: Auto-send
        // await sendMessage();
        messageInput.focus();
    });
});

// Update connection status in right panel
function updateRightPanelStatus(isOnline) {
    const connDot = document.getElementById('connectionDot');
    const connText = document.getElementById('statusText');
    if (connDot && connText) {
        if (isOnline) {
            connDot.classList.remove('offline');
            connDot.classList.add('online');
            connText.textContent = 'Online';
        } else {
            connDot.classList.remove('online');
            connDot.classList.add('offline');
            connText.textContent = 'Offline';
        }
    }
}

// Hook into existing setConnected function when available
if (typeof window.setConnected === 'function') {
    const originalSetConnected = window.setConnected;
    window.setConnected = function (isOnline) {
        originalSetConnected(isOnline);
        updateRightPanelStatus(isOnline);
    };
} else {
    // Safe default for index.html where setConnected may not be defined.
    updateRightPanelStatus(true);
}

console.log('ProjectForge initialized successfully! Ready for Python backend integration.');
checkHealth();
initTheme();
