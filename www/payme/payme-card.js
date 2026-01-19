/**
 * payme Lovelace Card for Home Assistant
 *
 * A custom card for managing bill payments with a clean table-based interface.
 */

class PaymeCard extends HTMLElement {
  static get properties() {
    return {
      hass: {},
      config: {},
    };
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._bills = [];
    this._history = [];
    this._selectedBill = null;
    this._activeTab = 'pending';
    this._clickHandlerBound = false;
  }

  connectedCallback() {
    if (!this._clickHandlerBound) {
      this.shadowRoot.addEventListener('click', (e) => this._handleClick(e), true);
      this._clickHandlerBound = true;
      console.log('PAYME: Click handler attached');
    }
  }

  _handleClick(e) {
    const target = e.target;
    console.log('Click target:', target.tagName, target.className);
    console.log('Selected bill:', this._selectedBill ? this._selectedBill.id : 'none');

    // Handle table row clicks
    const row = target.closest('.bill-row');
    if (row) {
      const billId = row.getAttribute('data-bill-id');
      if (billId) this._selectBill(billId);
      return;
    }

    // Check for button clicks
    const btn = target.closest('button');
    if (!btn) {
      // Also check for mwc-icon-button (refresh)
      const iconBtn = target.closest('mwc-icon-button');
      if (iconBtn && iconBtn.classList.contains('refresh-btn')) {
        this._poll();
      }
      return;
    }

    // Handle approve button
    if (btn.classList.contains('btn-primary') && this._selectedBill) {
      e.stopPropagation();
      console.log('Approve clicked for bill:', this._selectedBill.id);
      this._approveBill(this._selectedBill.id);
      return;
    }

    // Handle reject button
    if (btn.classList.contains('btn-danger') && this._selectedBill) {
      e.stopPropagation();
      console.log('Reject clicked for bill:', this._selectedBill.id);
      this._rejectBill(this._selectedBill.id);
      return;
    }

    // Handle back button
    if (btn.classList.contains('btn-back')) {
      this._closeDetail();
      return;
    }

    // Handle tab buttons
    if (btn.classList.contains('tab')) {
      const tabName = btn.getAttribute('data-tab');
      if (tabName) this._setActiveTab(tabName);
      return;
    }
  }

  setConfig(config) {
    this._config = config;
  }

  getCardSize() {
    return 8;
  }

  set hass(hass) {
    this._hass = hass;
    this._loadData();
    this._render();
  }

  _loadData() {
    if (!this._hass) return;

    // Load pending bills
    const pendingEntity = this._hass.states['sensor.payme_pending_bills'];
    if (pendingEntity && pendingEntity.attributes.bills) {
      try {
        this._bills = JSON.parse(pendingEntity.attributes.bills);
      } catch (e) {
        this._bills = [];
      }
    }

    // Load payment history
    const historyEntity = this._hass.states['sensor.payme_payment_history'];
    if (historyEntity && historyEntity.attributes.history) {
      try {
        this._history = JSON.parse(historyEntity.attributes.history);
      } catch (e) {
        this._history = [];
      }
    }

    // Load balance
    const balanceEntity = this._hass.states['sensor.payme_wise_balance'];
    this._balance = balanceEntity ? parseFloat(balanceEntity.state) : 0;
  }

  _getFilteredBills() {
    const allBills = [...this._bills, ...this._history];

    switch (this._activeTab) {
      case 'pending':
        return allBills.filter(b => b.status === 'pending');
      case 'processing':
        return allBills.filter(b => ['awaiting_2fa', 'awaiting_funding', 'processing', 'insufficient_balance'].includes(b.status));
      case 'complete':
        return allBills.filter(b => ['paid', 'rejected', 'failed'].includes(b.status));
      case 'all':
        // Sort by created_at descending for history view
        return [...allBills].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
      default:
        return allBills;
    }
  }

  _formatCurrency(amount, currency = 'EUR') {
    return new Intl.NumberFormat('de-DE', {
      style: 'currency',
      currency: currency
    }).format(amount);
  }

  _formatDate(dateStr) {
    if (!dateStr) return '-';
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
      });
    } catch (e) {
      return dateStr;
    }
  }

  _getStatusBadge(status) {
    const statusConfig = {
      'pending': { label: 'Pending', class: 'status-pending' },
      'awaiting_2fa': { label: 'Awaiting 2FA', class: 'status-processing' },
      'awaiting_funding': { label: 'Fund in Wise', class: 'status-processing' },
      'processing': { label: 'Processing', class: 'status-processing' },
      'insufficient_balance': { label: 'Needs Funding', class: 'status-warning' },
      'paid': { label: 'Paid', class: 'status-paid' },
      'rejected': { label: 'Rejected', class: 'status-rejected' },
      'failed': { label: 'Failed', class: 'status-failed' }
    };

    const config = statusConfig[status] || { label: status, class: 'status-pending' };
    return `<span class="status-badge ${config.class}">${config.label}</span>`;
  }

  _selectBill(billId) {
    const allBills = [...this._bills, ...this._history];
    this._selectedBill = allBills.find(b => b.id === billId) || null;
    this._render();
  }

  _closeDetail() {
    this._selectedBill = null;
    this._render();
  }

  async _approveBill(billId) {
    if (!this._hass) return;

    try {
      await this._hass.callService('pyscript', 'payme_approve', { bill_id: billId });
      this._closeDetail();
    } catch (e) {
      console.error('Failed to approve bill:', e);
    }
  }

  async _rejectBill(billId) {
    if (!this._hass) return;

    try {
      await this._hass.callService('pyscript', 'payme_reject', { bill_id: billId });
      this._closeDetail();
    } catch (e) {
      console.error('Failed to reject bill:', e);
    }
  }

  async _poll() {
    if (!this._hass) return;

    try {
      await this._hass.callService('pyscript', 'payme_poll');
    } catch (e) {
      console.error('Failed to poll:', e);
    }
  }

  _setActiveTab(tab) {
    this._activeTab = tab;
    this._render();
  }

  _getBalanceStatus() {
    const pendingBills = [...this._bills, ...this._history].filter(b => b.status === 'pending');

    if (pendingBills.length === 0) {
      return { state: 'good', message: 'No pending bills' };
    }

    // Sort bills by amount ascending to check how many we can pay
    const sortedBills = [...pendingBills].sort((a, b) => a.amount - b.amount);
    const totalPending = pendingBills.reduce((sum, b) => sum + b.amount, 0);

    // Check if we can pay all bills
    if (this._balance >= totalPending) {
      return { state: 'good', message: `Can pay all ${pendingBills.length} bill${pendingBills.length > 1 ? 's' : ''}` };
    }

    // Check how many bills we can pay (starting from smallest)
    let remaining = this._balance;
    let canPay = 0;
    for (const bill of sortedBills) {
      if (remaining >= bill.amount) {
        remaining -= bill.amount;
        canPay++;
      } else {
        break;
      }
    }

    if (canPay === 0) {
      // Cannot pay any bills
      const smallest = sortedBills[0];
      const needed = smallest.amount - this._balance;
      return { state: 'low', message: `Need ${this._formatCurrency(needed)} more` };
    } else {
      // Can pay some but not all
      return { state: 'medium', message: `Can pay ${canPay} of ${pendingBills.length} bills` };
    }
  }

  _render() {
    const bills = this._getFilteredBills();
    const pendingCount = [...this._bills, ...this._history].filter(b => b.status === 'pending').length;
    const processingCount = [...this._bills, ...this._history].filter(b => ['awaiting_2fa', 'awaiting_funding', 'processing', 'insufficient_balance'].includes(b.status)).length;
    const completeCount = [...this._bills, ...this._history].filter(b => ['paid', 'rejected', 'failed'].includes(b.status)).length;
    const allCount = [...this._bills, ...this._history].length;

    const balanceStatus = this._getBalanceStatus();

    this.shadowRoot.innerHTML = `
      <style>${this._getStyles()}</style>

      <ha-card>
        <div class="card-header">
          <div class="header-title">
            <span class="title">Bills</span>
          </div>
          <mwc-icon-button class="refresh-btn" @click="${() => this._poll()}">
            <ha-icon icon="mdi:refresh"></ha-icon>
          </mwc-icon-button>
        </div>

        <div class="balance-bar ${balanceStatus.state}">
          <div class="balance-amount">${this._formatCurrency(this._balance)}</div>
        </div>

        <div class="tabs">
          <button class="tab ${this._activeTab === 'pending' ? 'active' : ''}" data-tab="pending">
            Pending <span class="badge">${pendingCount}</span>
          </button>
          <button class="tab ${this._activeTab === 'processing' ? 'active' : ''}" data-tab="processing">
            Processing <span class="badge">${processingCount}</span>
          </button>
          <button class="tab ${this._activeTab === 'complete' ? 'active' : ''}" data-tab="complete">
            Complete <span class="badge">${completeCount}</span>
          </button>
          <button class="tab ${this._activeTab === 'all' ? 'active' : ''}" data-tab="all">
            All <span class="badge">${allCount}</span>
          </button>
        </div>

        <div class="card-content">
          ${this._selectedBill ? this._renderDetail() : this._renderTable(bills)}
        </div>
      </ha-card>
    `;

    // Event delegation handles all clicks - see _handleClick()
  }

  _renderTable(bills) {
    if (bills.length === 0) {
      return `
        <div class="empty-state">
          <ha-icon icon="mdi:file-document-outline"></ha-icon>
          <p>No bills in this category</p>
        </div>
      `;
    }

    return `
      <div class="table-container">
        <table class="bills-table">
          <thead>
            <tr>
              <th>Due</th>
              <th>Vendor</th>
              <th class="align-right">Amount</th>
              <th>Status</th>
              <th>Paid</th>
            </tr>
          </thead>
          <tbody>
            ${bills.map(bill => `
              <tr class="bill-row ${bill.duplicate_warning ? 'warning' : ''} ${bill.low_confidence ? 'low-confidence' : ''}"
                  data-bill-id="${bill.id}">
                <td class="date-cell">${this._formatDate(bill.due_date)}</td>
                <td>
                  <div class="vendor-cell">
                    <span class="vendor-name">${this._escapeHtml(bill.recipient)}</span>
                    ${bill.description ? `<span class="vendor-desc">${this._escapeHtml(bill.description)}</span>` : ''}
                  </div>
                </td>
                <td class="amount align-right">${this._formatCurrency(bill.amount, bill.currency)}</td>
                <td>${bill.status !== 'paid' ? this._getStatusBadge(bill.status) : ''}</td>
                <td class="date-cell">${this._formatDate(bill.paid_at)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  _renderDetail() {
    const bill = this._selectedBill;
    if (!bill) return '';

    const isPending = bill.status === 'pending';

    return `
      <div class="bill-detail">
        <div class="detail-header">
          <button class="btn-back">
            <ha-icon icon="mdi:arrow-left"></ha-icon> Back
          </button>
        </div>

        <div class="detail-title">
          <h2>${this._escapeHtml(bill.recipient)}</h2>
          ${this._getStatusBadge(bill.status)}
        </div>

        <div class="amount-display">
          ${this._formatCurrency(bill.amount, bill.currency)}
        </div>

        ${isPending ? `
          <div class="action-buttons">
            <button class="btn btn-primary">
              <ha-icon icon="mdi:check"></ha-icon> Approve
            </button>
            <button class="btn btn-danger">
              <ha-icon icon="mdi:close"></ha-icon> Reject
            </button>
          </div>
        ` : ''}

        ${bill.duplicate_warning ? `
          <div class="warning-banner">
            <ha-icon icon="mdi:alert"></ha-icon> Possible duplicate payment
          </div>
        ` : ''}

        ${bill.low_confidence ? `
          <div class="warning-banner">
            <ha-icon icon="mdi:alert"></ha-icon> Low confidence - verify details
          </div>
        ` : ''}

        <div class="detail-section">
          <h3>Payment Details</h3>
          <dl class="detail-list">
            <dt>Bank</dt>
            <dd>${this._escapeHtml(bill.bank_name || 'Unknown')}</dd>

            <dt>IBAN</dt>
            <dd class="mono">${this._formatIban(bill.iban)}</dd>

            ${bill.bic ? `
              <dt>BIC</dt>
              <dd class="mono">${this._escapeHtml(bill.bic)}</dd>
            ` : ''}

            <dt>Reference</dt>
            <dd>${this._escapeHtml(bill.reference || '-')}</dd>

            ${bill.invoice_number ? `
              <dt>Invoice</dt>
              <dd>${this._escapeHtml(bill.invoice_number)}</dd>
            ` : ''}

            ${bill.due_date ? `
              <dt>Due Date</dt>
              <dd>${this._formatDate(bill.due_date)}</dd>
            ` : ''}
          </dl>
        </div>

        ${bill.english_translation ? `
          <div class="detail-section">
            <h3>English Translation</h3>
            <div class="translation-text">
              ${this._escapeHtml(bill.english_translation).replace(/\n/g, '<br>')}
            </div>
          </div>
        ` : ''}

        ${bill.original_text ? `
          <div class="detail-section">
            <h3>Original Text</h3>
            <div class="original-text">
              ${this._escapeHtml(bill.original_text).replace(/\n/g, '<br>')}
            </div>
          </div>
        ` : ''}

        <div class="detail-section metadata">
          <h3>Info</h3>
          <dl class="detail-list small">
            <dt>Source</dt>
            <dd>${bill.source === 'girocode' ? 'QR Code' : 'Gemini OCR'}</dd>

            <dt>Confidence</dt>
            <dd>${Math.round(bill.confidence * 100)}%</dd>

            <dt>Created</dt>
            <dd>${this._formatDate(bill.created_at)}</dd>

            ${bill.paid_at ? `
              <dt>Paid</dt>
              <dd>${this._formatDate(bill.paid_at)}</dd>
            ` : ''}
          </dl>
        </div>
      </div>
    `;
  }

  _formatIban(iban) {
    if (!iban) return '-';
    return iban.replace(/(.{4})/g, '$1 ').trim();
  }

  _escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  _getStyles() {
    return `
      :host {
        --payme-primary: var(--primary-color, #03a9f4);
        --payme-text: var(--primary-text-color, #212121);
        --payme-text-secondary: var(--secondary-text-color, #757575);
        --payme-divider: var(--divider-color, #e0e0e0);
        --payme-surface: var(--card-background-color, #fff);
        --payme-surface-variant: var(--secondary-background-color, #f5f5f5);
      }

      ha-card {
        overflow: hidden;
      }

      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px;
        border-bottom: 1px solid var(--payme-divider);
      }

      .header-title {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }

      .title {
        font-size: 18px;
        font-weight: 500;
        color: var(--payme-text);
      }

      .balance {
        font-size: 13px;
        color: var(--payme-text-secondary);
      }

      .refresh-btn {
        --mdc-icon-button-size: 36px;
        color: var(--payme-text-secondary);
      }

      /* Balance Bar */
      .balance-bar {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 20px;
      }

      .balance-bar.good { background: #4caf50; }
      .balance-bar.medium { background: #ff9800; }
      .balance-bar.low { background: #f44336; }

      .balance-amount {
        font-size: 32px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: white;
      }

      /* Tabs */
      .tabs {
        display: flex;
        border-bottom: 1px solid var(--payme-divider);
        padding: 0 8px;
      }

      .tab {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 12px 16px;
        background: none;
        border: none;
        border-bottom: 2px solid transparent;
        margin-bottom: -1px;
        font-size: 13px;
        font-weight: 500;
        color: var(--payme-text-secondary);
        cursor: pointer;
      }

      .tab:hover {
        color: var(--payme-text);
      }

      .tab.active {
        color: var(--payme-primary);
        border-bottom-color: var(--payme-primary);
      }

      .badge {
        background: var(--payme-surface-variant);
        padding: 2px 6px;
        border-radius: 10px;
        font-size: 11px;
      }

      .tab.active .badge {
        background: var(--payme-primary);
        color: white;
      }

      /* Table */
      .card-content {
        padding: 0;
      }

      .table-container {
        overflow-x: auto;
      }

      .bills-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }

      .bills-table th {
        text-align: left;
        padding: 10px 16px;
        font-weight: 500;
        color: var(--payme-text-secondary);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .bills-table td {
        padding: 12px 16px;
        border-top: 1px solid var(--payme-divider);
        vertical-align: middle;
      }

      .align-right {
        text-align: right;
      }

      .bill-row {
        cursor: pointer;
        transition: background-color 0.15s;
      }

      .bill-row:hover {
        background: var(--payme-surface-variant);
      }

      .bill-row.warning {
        background: rgba(255, 152, 0, 0.1);
      }

      .date-cell {
        white-space: nowrap;
        color: var(--payme-text-secondary);
        font-size: 12px;
      }

      .vendor-cell {
        display: flex;
        flex-direction: column;
        gap: 1px;
      }

      .vendor-name {
        font-weight: 500;
        color: var(--payme-text);
      }

      .vendor-desc {
        font-size: 11px;
        color: var(--payme-text-secondary);
      }

      .amount {
        font-weight: 500;
        font-variant-numeric: tabular-nums;
      }

      /* Status Badges */
      .status-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 500;
      }

      .status-pending { background: #e3f2fd; color: #1976d2; }
      .status-processing { background: #fff3e0; color: #f57c00; }
      .status-warning { background: #fff8e1; color: #ffa000; }
      .status-paid { background: #e8f5e9; color: #388e3c; }
      .status-rejected { background: #fce4ec; color: #c2185b; }
      .status-failed { background: #ffebee; color: #d32f2f; }

      /* Empty State */
      .empty-state {
        text-align: center;
        padding: 40px 20px;
        color: var(--payme-text-secondary);
      }

      .empty-state ha-icon {
        --mdc-icon-size: 48px;
        opacity: 0.4;
        margin-bottom: 8px;
      }

      /* Detail View */
      .bill-detail {
        padding: 16px;
      }

      .detail-header {
        margin-bottom: 12px;
      }

      .btn-back {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background: none;
        border: none;
        color: var(--payme-primary);
        cursor: pointer;
        padding: 0;
        font-size: 13px;
      }

      .btn-back ha-icon {
        --mdc-icon-size: 18px;
      }

      .detail-title {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 8px;
      }

      .detail-title h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 500;
      }

      .amount-display {
        font-size: 32px;
        font-weight: 500;
        margin-bottom: 16px;
        color: var(--payme-text);
      }

      .action-buttons {
        display: flex;
        gap: 8px;
        margin-bottom: 16px;
      }

      .btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 10px 20px;
        border: none;
        border-radius: 4px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
      }

      .btn ha-icon {
        --mdc-icon-size: 18px;
      }

      .btn-primary {
        background: var(--payme-primary);
        color: white;
        flex: 1;
      }

      .btn-danger {
        background: #f44336;
        color: white;
      }

      .warning-banner {
        display: flex;
        align-items: center;
        gap: 8px;
        background: #fff3e0;
        border-radius: 4px;
        padding: 10px 12px;
        margin-bottom: 16px;
        font-size: 13px;
        color: #e65100;
      }

      .warning-banner ha-icon {
        --mdc-icon-size: 18px;
      }

      .detail-section {
        margin-bottom: 20px;
      }

      .detail-section h3 {
        font-size: 12px;
        font-weight: 500;
        color: var(--payme-text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin: 0 0 10px 0;
      }

      .detail-list {
        display: grid;
        grid-template-columns: 80px 1fr;
        gap: 6px 12px;
        margin: 0;
        font-size: 13px;
      }

      .detail-list dt {
        color: var(--payme-text-secondary);
      }

      .detail-list dd {
        margin: 0;
        color: var(--payme-text);
      }

      .detail-list.small {
        font-size: 12px;
      }

      .mono {
        font-family: 'Roboto Mono', monospace;
        font-size: 12px;
      }

      .translation-text {
        font-size: 13px;
        line-height: 1.5;
        color: var(--payme-text);
        background: var(--payme-surface-variant);
        padding: 12px;
        border-radius: 4px;
      }

      .original-text {
        font-size: 12px;
        line-height: 1.5;
        color: var(--payme-text-secondary);
        font-style: italic;
        background: var(--payme-surface-variant);
        padding: 12px;
        border-radius: 4px;
      }

      .metadata {
        opacity: 0.8;
      }
    `;
  }
}

customElements.define('payme-card', PaymeCard);

// Register card with Home Assistant
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'payme-card',
  name: 'payme Bills',
  description: 'Manage bill payments with approval workflow',
  preview: true,
});

console.info('%c PAYME-CARD %c loaded ', 'background: #03a9f4; color: white; font-weight: bold;', 'background: #eee;');
