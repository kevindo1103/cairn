const SHOPIFY_API_VERSION = '2024-10';
const BANK = { account: '918668899', name: 'MBBank', holder: 'CONG TY CO PHAN THE VIA' };
const PAYMENT_PREFIX = 'DH';
const PAYMENT_TIMEOUT_MS = 30 * 60 * 1000; // 30 phút
const POLL_INTERVAL_MS = 5000;

// ── Crypto helpers ──────────────────────────────────────────────

async function createToken(payload, secret) {
  const data = btoa(unescape(encodeURIComponent(JSON.stringify({ ...payload, exp: Date.now() + 3600000 }))));
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(sig)));
  return data + '.' + sigB64;
}

async function verifyToken(token, secret) {
  const parts = token.split('.');
  if (parts.length !== 2) throw new Error('Invalid token format');
  const [data, sig] = parts;
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify']);
  const sigBytes = Uint8Array.from(atob(sig), c => c.charCodeAt(0));
  const valid = await crypto.subtle.verify('HMAC', key, sigBytes, new TextEncoder().encode(data));
  if (!valid) throw new Error('Invalid token');
  const payload = JSON.parse(decodeURIComponent(escape(atob(data))));
  if (payload.exp < Date.now()) throw new Error('Token expired');
  return payload;
}

// ── Shopify API ─────────────────────────────────────────────────

async function shopifyAPI(env, method, endpoint, body) {
  const res = await fetch(`https://${env.SHOPIFY_STORE}/admin/api/${SHOPIFY_API_VERSION}${endpoint}`, {
    method,
    headers: { 'X-Shopify-Access-Token': env.SHOPIFY_ACCESS_TOKEN, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    if (res.status === 422) throw new Error('SHOPIFY_VALIDATION:' + text);
    throw new Error(`Shopify ${res.status}: ${text}`);
  }
  return res.json();
}

// ── CORS ────────────────────────────────────────────────────────

function corsHeaders(env, request) {
  const origin = request ? (request.headers.get('Origin') || '') : '';
  const allowed = (env.ALLOWED_ORIGIN || '').split(',').map(s => s.trim());
  allowed.push('https://theviatea.com', 'https://www.theviatea.com');
  const match = allowed.includes(origin) ? origin : allowed[0];
  return {
    'Access-Control-Allow-Origin': match,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function jsonResponse(data, env, status = 200, request = null) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders(env, request), 'Content-Type': 'application/json' },
  });
}

// ── POST /api/start-checkout ────────────────────────────────────

async function handleStartCheckout(request, env) {
  const body = await request.json();
  const items = (body.items || []).map(i => ({
    variant_id: i.variant_id || i.id,
    quantity: i.quantity,
    title: i.title || i.product_title || '',
    price: i.price || i.line_price || 0,
    image: i.image || i.featured_image?.url || '',
  }));
  const totalPrice = body.total_price || items.reduce((s, i) => s + i.price * i.quantity, 0);

  const token = await createToken({ items, total_price: totalPrice }, env.JWT_SECRET);
  return jsonResponse({ redirect: `/pay?token=${encodeURIComponent(token)}` }, env, 200, request);
}

// ── GET /pay?token=xxx ──────────────────────────────────────────

async function handlePaymentPage(url, env) {
  const token = url.searchParams.get('token');
  if (!token) {
    return new Response(renderErrorHTML('Thiếu thông tin thanh toán', 'Vui lòng quay lại giỏ hàng và thử lại.'), {
      status: 400, headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }

  let cart;
  try {
    cart = await verifyToken(token, env.JWT_SECRET);
  } catch {
    return new Response(renderErrorHTML('Phiên thanh toán đã hết hạn', 'Vui lòng quay lại giỏ hàng và thực hiện lại.'), {
      status: 400, headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }

  return new Response(renderPaymentHTML(cart, token, env), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

// ── POST /api/create-order ──────────────────────────────────────

async function handleCreateOrder(request, env) {
  const { token, customer } = await request.json();

  let cart;
  try {
    cart = await verifyToken(token, env.JWT_SECRET);
  } catch {
    return jsonResponse({ error: 'Phiên thanh toán đã hết hạn. Vui lòng quay lại giỏ hàng.' }, env, 401, request);
  }

  const lineItems = cart.items.map(i => ({ variant_id: i.variant_id, quantity: i.quantity }));

  const address = {
    first_name: customer.first_name || '',
    last_name: customer.last_name || '',
    address1: customer.address1 || '',
    city: customer.city || '',
    province: customer.province || '',
    zip: customer.zip || '',
    country: 'VN',
    phone: customer.phone || '',
  };

  let result;
  try {
    result = await shopifyAPI(env, 'POST', '/orders.json', {
      order: {
        email: customer.email,
        financial_status: 'pending',
        send_receipt: true,
        line_items: lineItems,
        shipping_address: address,
        billing_address: address,
        shipping_lines: [{ title: 'Standard', price: '0.00', code: 'Standard' }],
        tags: 'sepay-qr,chuyen-khoan',
      },
    });
  } catch (err) {
    if (err.message.startsWith('SHOPIFY_VALIDATION:')) {
      return jsonResponse({ error: 'Một số sản phẩm đã hết hàng hoặc không khả dụng. Vui lòng quay lại giỏ hàng.' }, env, 422, request);
    }
    return jsonResponse({ error: 'Không thể tạo đơn hàng. Vui lòng thử lại.' }, env, 500, request);
  }

  const order = result.order;
  const totalVND = Math.round(parseFloat(order.total_price));
  const content = PAYMENT_PREFIX + order.order_number;

  return jsonResponse({
    order_id: order.id,
    order_number: order.order_number,
    order_name: order.name,
    total_price: totalVND,
    content,
    qr_url: `https://qr.sepay.vn/img?acc=${BANK.account}&bank=${BANK.name}&amount=${totalVND}&des=${encodeURIComponent(content)}`,
    order_status_url: order.order_status_url || '',
  }, env, 200, request);
}

// ── GET /api/status/:orderId ────────────────────────────────────

async function handleCheckStatus(url, env) {
  const orderId = url.pathname.split('/').pop();
  const result = await shopifyAPI(env, 'GET', `/orders/${orderId}.json?fields=id,financial_status,order_status_url`);
  return jsonResponse({
    paid: result.order.financial_status === 'paid',
    financial_status: result.order.financial_status,
    order_status_url: result.order.order_status_url || '',
  }, env);
}

// ── HTML helpers ────────────────────────────────────────────────

function escapeHTML(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatVND(cents) {
  const vnd = Math.round(cents / 100);
  return vnd.toLocaleString('vi-VN');
}

// ── Error page ──────────────────────────────────────────────────

function renderErrorHTML(title, message) {
  return `<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHTML(title)} - THÉVIA TEA</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Cormorant Garamond',Georgia,'Times New Roman',serif;background:#1b1b1b;color:#e8dcc8;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center}
.error-box{text-align:center;padding:48px 32px;max-width:480px}
.error-icon{font-size:64px;margin-bottom:24px;opacity:0.6}
h1{font-size:24px;font-weight:400;letter-spacing:1px;margin-bottom:16px;color:#c9a96e}
p{font-size:16px;line-height:1.6;color:#a09880;margin-bottom:32px}
a{display:inline-block;padding:14px 32px;background:#c9a96e;color:#1b1b1b;text-decoration:none;font-size:15px;letter-spacing:1px;transition:all 0.3s}
a:hover{background:#d4b87a}
</style>
</head>
<body>
<div class="error-box">
  <div class="error-icon">&#9888;</div>
  <h1>${escapeHTML(title)}</h1>
  <p>${escapeHTML(message)}</p>
  <a href="https://theviatea.com/cart">Quay lại giỏ hàng</a>
</div>
</body>
</html>`;
}

// ── Payment page ────────────────────────────────────────────────

function renderPaymentHTML(cart, token, env) {
  const totalDisplay = formatVND(cart.total_price);

  const itemsHTML = cart.items.map(i => {
    const imgHTML = i.image
      ? `<img src="${escapeHTML(i.image)}" alt="" style="width:56px;height:56px;object-fit:cover;border-radius:4px;border:1px solid #3a3a3a">`
      : `<div style="width:56px;height:56px;background:#2a2a2a;border-radius:4px;display:flex;align-items:center;justify-content:center;color:#666;font-size:20px">&#9733;</div>`;
    return `
    <div class="order-item">
      ${imgHTML}
      <div class="order-item-info">
        <div class="order-item-title">${escapeHTML(i.title)}</div>
        <div class="order-item-qty">Số lượng: ${i.quantity}</div>
      </div>
      <div class="order-item-price">${formatVND(i.price * i.quantity)}đ</div>
    </div>`;
  }).join('');

  const workerOrigin = env.WORKER_URL || '';

  return `<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Thanh toán - THÉVIA TEA</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Cormorant Garamond',Georgia,'Times New Roman',serif;background:#1b1b1b;color:#e8dcc8;min-height:100vh}

/* Header */
.header{background:#111;border-bottom:1px solid #2a2a2a;padding:20px 24px;text-align:center}
.header-logo{font-size:22px;font-weight:300;letter-spacing:4px;color:#c9a96e;text-transform:uppercase}
.header-logo span{display:block;font-size:11px;letter-spacing:6px;color:#8a7a60;margin-top:4px;font-weight:400}
.header-nav{margin-top:12px}
.header-nav a{color:#8a8a8a;text-decoration:none;font-size:13px;letter-spacing:1px;margin:0 12px;transition:color 0.3s}
.header-nav a:hover{color:#c9a96e}

/* Progress steps */
.progress{display:flex;justify-content:center;align-items:center;padding:24px 16px;gap:8px}
.progress-step{display:flex;align-items:center;gap:8px;font-size:13px;letter-spacing:1px;color:#555}
.progress-step.active{color:#c9a96e}
.progress-step.done{color:#6b9e6d}
.progress-num{width:28px;height:28px;border-radius:50%;border:1px solid #444;display:flex;align-items:center;justify-content:center;font-size:12px}
.progress-step.active .progress-num{border-color:#c9a96e;background:#c9a96e;color:#1b1b1b}
.progress-step.done .progress-num{border-color:#6b9e6d;background:#6b9e6d;color:#1b1b1b}
.progress-line{width:40px;height:1px;background:#333}

/* Layout */
.container{max-width:1000px;margin:0 auto;padding:0 16px 48px;display:grid;grid-template-columns:1fr;gap:24px}
@media(min-width:768px){.container{grid-template-columns:1fr 380px}}

/* Cards */
.card{background:#222;border:1px solid #2e2e2e;border-radius:8px;padding:28px}
.card-title{font-size:20px;font-weight:400;color:#c9a96e;letter-spacing:1px;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid #333}

/* Form */
.form-group{margin-bottom:18px}
.form-group label{display:block;font-size:13px;letter-spacing:1px;color:#8a8a8a;margin-bottom:6px;text-transform:uppercase}
.form-group input{width:100%;padding:12px 14px;background:#1b1b1b;border:1px solid #3a3a3a;border-radius:4px;color:#e8dcc8;font-size:15px;font-family:inherit;transition:border-color 0.3s}
.form-group input:focus{outline:none;border-color:#c9a96e}
.form-group input::placeholder{color:#555}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}

/* Button */
.btn-primary{width:100%;padding:16px;background:#c9a96e;color:#1b1b1b;border:none;font-family:inherit;font-size:15px;font-weight:600;letter-spacing:2px;cursor:pointer;transition:all 0.3s;text-transform:uppercase;margin-top:8px}
.btn-primary:hover{background:#d4b87a}
.btn-primary:disabled{background:#444;color:#777;cursor:not-allowed}
.btn-back{display:inline-block;padding:14px 32px;background:transparent;border:1px solid #c9a96e;color:#c9a96e;text-decoration:none;font-family:inherit;font-size:14px;letter-spacing:1px;transition:all 0.3s;cursor:pointer;text-align:center}
.btn-back:hover{background:#c9a96e;color:#1b1b1b}

/* Order summary */
.order-item{display:flex;align-items:center;gap:14px;padding:14px 0;border-bottom:1px solid #2e2e2e}
.order-item:last-child{border-bottom:none}
.order-item-info{flex:1;min-width:0}
.order-item-title{font-size:15px;color:#e8dcc8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.order-item-qty{font-size:13px;color:#8a8a8a;margin-top:4px}
.order-item-price{font-size:15px;color:#c9a96e;font-weight:600;white-space:nowrap}
.order-total{display:flex;justify-content:space-between;padding:16px 0 0;margin-top:8px;border-top:1px solid #c9a96e}
.order-total span:first-child{font-size:16px;letter-spacing:1px}
.order-total span:last-child{font-size:20px;color:#c9a96e;font-weight:700}

/* QR section */
.qr-section{text-align:center}
.qr-order-tag{display:inline-block;background:#c9a96e;color:#1b1b1b;padding:6px 16px;font-size:13px;font-weight:600;letter-spacing:2px;margin-bottom:20px}
.qr-img{width:200px;height:200px;margin:0 auto 24px;display:block;border-radius:8px;border:2px solid #c9a96e;padding:4px;background:#fff}
.bank-table{width:100%;text-align:left;margin:0 auto;max-width:360px}
.bank-table td{padding:8px 12px;font-size:14px;border-bottom:1px solid #2e2e2e}
.bank-table td:first-child{color:#8a8a8a;width:40%}
.bank-table td:last-child{color:#e8dcc8;font-weight:500}
.bank-table .highlight{color:#e74c3c;font-weight:700;font-size:15px}
.bank-table .amount{color:#c9a96e;font-weight:700;font-size:15px}
.bank-warning{background:#2a2016;border:1px solid #c9a96e33;border-radius:6px;padding:14px;margin-top:20px;font-size:13px;color:#c9a96e;line-height:1.5}

/* Status */
.status-bar{text-align:center;padding:16px;border-radius:6px;margin-top:20px;font-size:14px;display:flex;align-items:center;justify-content:center;gap:10px}
.status-pending{background:#2a2016;border:1px solid #c9a96e44;color:#c9a96e}
.status-timeout{background:#2a1616;border:1px solid #e74c3c44;color:#e74c3c}
.status-paid{background:#162a1a;border:1px solid #6b9e6d44;color:#6b9e6d}
.countdown{font-weight:600;font-variant-numeric:tabular-nums}
.spinner{width:16px;height:16px;border:2px solid transparent;border-top-color:currentColor;border-radius:50%;animation:spin 1s linear infinite;flex-shrink:0}
@keyframes spin{to{transform:rotate(360deg)}}

/* Success */
.success-section{text-align:center;padding:48px 24px}
.success-icon{width:80px;height:80px;border-radius:50%;background:#6b9e6d;color:#1b1b1b;font-size:36px;display:flex;align-items:center;justify-content:center;margin:0 auto 24px}
.success-title{font-size:28px;color:#c9a96e;font-weight:400;letter-spacing:1px;margin-bottom:12px}
.success-msg{color:#8a8a8a;font-size:15px;margin-bottom:32px;line-height:1.6}

/* Steps */
.step{display:none}.step.active{display:block}
.error-msg{color:#e74c3c;font-size:14px;margin-top:8px;padding:10px;background:#2a1616;border-radius:4px;border:1px solid #e74c3c33}

/* Footer */
.footer{text-align:center;padding:32px 16px;border-top:1px solid #2a2a2a;margin-top:48px}
.footer-text{font-size:12px;color:#555;letter-spacing:1px}
.footer-contact{margin-top:8px;font-size:12px;color:#666}
.footer-contact a{color:#c9a96e;text-decoration:none}

/* Mobile */
@media(max-width:767px){
  .container{padding:0 12px 32px}
  .card{padding:20px}
  .qr-img{width:180px;height:180px}
  .progress-line{width:20px}
  .header-nav{display:none}
}
</style>
</head>
<body>

<div class="header">
  <div class="header-logo">
    THÉVIA TEA
    <span>The Way of Tea</span>
  </div>
</div>

<div class="progress">
  <div class="progress-step done" id="pStep1"><span class="progress-num">1</span> Giỏ hàng</div>
  <div class="progress-line"></div>
  <div class="progress-step active" id="pStep2"><span class="progress-num">2</span> Thông tin</div>
  <div class="progress-line"></div>
  <div class="progress-step" id="pStep3"><span class="progress-num">3</span> Thanh toán</div>
  <div class="progress-line"></div>
  <div class="progress-step" id="pStep4"><span class="progress-num">4</span> Hoàn tất</div>
</div>

<div class="container">
  <div>
    <!-- Step 1: Customer info -->
    <div id="step1" class="card step active">
      <div class="card-title">Thông tin giao hàng</div>
      <form id="customerForm">
        <div class="form-group">
          <label>Email</label>
          <input type="email" name="email" required placeholder="email@example.com" autocomplete="email">
        </div>
        <div class="row">
          <div class="form-group">
            <label>Họ</label>
            <input type="text" name="last_name" required placeholder="Nguyễn" autocomplete="family-name">
          </div>
          <div class="form-group">
            <label>Tên</label>
            <input type="text" name="first_name" required placeholder="Văn A" autocomplete="given-name">
          </div>
        </div>
        <div class="form-group">
          <label>Số điện thoại</label>
          <input type="tel" name="phone" required placeholder="0912345678" autocomplete="tel">
        </div>
        <div class="form-group">
          <label>Địa chỉ</label>
          <input type="text" name="address1" required placeholder="Số nhà, đường" autocomplete="street-address">
        </div>
        <div class="row">
          <div class="form-group">
            <label>Quận/Huyện</label>
            <input type="text" name="province" placeholder="Quận Ba Đình">
          </div>
          <div class="form-group">
            <label>Thành phố</label>
            <input type="text" name="city" required placeholder="Hà Nội" autocomplete="address-level2">
          </div>
        </div>
        <div id="formError" class="error-msg" style="display:none"></div>
        <button type="submit" class="btn-primary" id="submitBtn">Tiếp tục thanh toán</button>
      </form>
    </div>

    <!-- Step 2: QR Payment -->
    <div id="step2" class="card step">
      <div class="qr-section">
        <div class="card-title" style="text-align:center;border-bottom:none;padding-bottom:0">Quét mã QR để thanh toán</div>
        <div class="qr-order-tag" id="orderTag">Đơn hàng</div>
        <img id="qrImage" class="qr-img" src="" alt="QR Code thanh toán">
        <table class="bank-table">
          <tr><td>Ngân hàng</td><td>${BANK.name}</td></tr>
          <tr><td>Số tài khoản</td><td>${BANK.account}</td></tr>
          <tr><td>Chủ TK</td><td>${BANK.holder}</td></tr>
          <tr><td>Số tiền</td><td class="amount" id="payAmount"></td></tr>
          <tr><td>Nội dung CK</td><td class="highlight" id="payContent"></td></tr>
        </table>
        <div class="bank-warning">
          &#9888; Vui lòng chuyển khoản <strong>đúng số tiền</strong> và <strong>đúng nội dung</strong> để đơn hàng được xác nhận tự động.
        </div>
      </div>
      <div id="paymentStatus" class="status-bar status-pending">
        <div class="spinner"></div>
        <span>Đang chờ thanh toán... Tự động xác nhận khi nhận được tiền.</span>
      </div>
      <div id="countdownBar" class="status-bar" style="display:none;margin-top:8px;font-size:13px;color:#8a8a8a">
        Thời gian còn lại: <span class="countdown" id="countdown">30:00</span>
      </div>
    </div>

    <!-- Step 3: Success -->
    <div id="step3" class="card step">
      <div class="success-section">
        <div class="success-icon">&#10004;</div>
        <div class="success-title">Thanh toán thành công!</div>
        <p class="success-msg">Đơn hàng của bạn đã được xác nhận.<br>Bạn sẽ nhận được email xác nhận trong ít phút.</p>
        <a id="orderLink" href="#" class="btn-primary" style="display:inline-block;text-decoration:none;max-width:320px">Xem đơn hàng</a>
        <div style="margin-top:16px">
          <a href="https://theviatea.com" class="btn-back">Tiếp tục mua sắm</a>
        </div>
      </div>
    </div>

    <!-- Step 4: Timeout -->
    <div id="step4" class="card step">
      <div class="success-section">
        <div class="success-icon" style="background:#e74c3c">&#9888;</div>
        <div class="success-title" style="color:#e74c3c">Hết thời gian chờ</div>
        <p class="success-msg">
          Nếu bạn đã chuyển khoản, đơn hàng sẽ được xác nhận tự động khi hệ thống nhận được tiền.<br><br>
          Nếu chưa chuyển khoản, vui lòng quay lại giỏ hàng và thực hiện lại.
        </p>
        <div style="margin-bottom:16px">
          <a id="orderLinkTimeout" href="#" class="btn-primary" style="display:inline-block;text-decoration:none;max-width:320px">Xem trạng thái đơn hàng</a>
        </div>
        <a href="https://theviatea.com/cart" class="btn-back">Quay lại giỏ hàng</a>
        <div style="margin-top:24px;font-size:13px;color:#8a8a8a">
          Cần hỗ trợ? Liên hệ <a href="mailto:contact@theviatea.com" style="color:#c9a96e">contact@theviatea.com</a> hoặc gọi <a href="tel:0982430125" style="color:#c9a96e">098 243 0125</a>
        </div>
      </div>
    </div>
  </div>

  <!-- Right: Order summary -->
  <div class="card" style="align-self:start;position:sticky;top:24px">
    <div class="card-title">Đơn hàng của bạn</div>
    ${itemsHTML}
    <div class="order-total">
      <span>Tổng cộng</span>
      <span>${totalDisplay}đ</span>
    </div>
  </div>
</div>

<div class="footer">
  <div class="footer-text">THÉVIA TEA &mdash; Thương hiệu Việt tôn vinh tinh hoa trà đạo</div>
  <div class="footer-contact">
    Hotline: <a href="tel:0982430125">098 243 0125</a> &middot; Email: <a href="mailto:contact@theviatea.com">contact@theviatea.com</a>
  </div>
</div>

<script>
var TOKEN = '${token.replace(/'/g, "\\'")}';
var API_BASE = '${workerOrigin}';
var TIMEOUT_MS = ${PAYMENT_TIMEOUT_MS};
var POLL_MS = ${POLL_INTERVAL_MS};
var pollTimer = null;
var countdownTimer = null;
var pollRetries = 0;
var MAX_POLL_RETRIES = 3;

function showStep(n) {
  ['step1','step2','step3','step4'].forEach(function(id) {
    document.getElementById(id).classList.remove('active');
  });
  document.getElementById('step' + n).classList.add('active');

  var steps = [
    {el: 'pStep1', done: n > 1},
    {el: 'pStep2', active: n === 1, done: n > 1},
    {el: 'pStep3', active: n === 2, done: n > 2},
    {el: 'pStep4', active: n >= 3, done: false},
  ];
  steps.forEach(function(s) {
    var el = document.getElementById(s.el);
    el.className = 'progress-step' + (s.done ? ' done' : '') + (s.active ? ' active' : '');
  });
}

document.getElementById('customerForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  var btn = document.getElementById('submitBtn');
  var errEl = document.getElementById('formError');
  btn.disabled = true;
  btn.textContent = 'Đang tạo đơn hàng...';
  errEl.style.display = 'none';

  var fd = new FormData(this);
  var customer = {};
  fd.forEach(function(v, k) { customer[k] = v; });

  try {
    var res = await fetch(API_BASE + '/api/create-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: TOKEN, customer: customer }),
    });

    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Lỗi tạo đơn hàng');

    window._orderId = data.order_id;
    window._orderStatusUrl = data.order_status_url;

    document.getElementById('qrImage').src = data.qr_url;
    document.getElementById('orderTag').textContent = 'Đơn hàng ' + data.order_name;
    document.getElementById('payAmount').textContent = data.total_price.toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('payContent').textContent = data.content;
    document.getElementById('orderLink').href = data.order_status_url || '#';
    document.getElementById('orderLinkTimeout').href = data.order_status_url || '#';

    showStep(2);
    document.getElementById('countdownBar').style.display = 'flex';
    startCountdown();
    startPolling(data.order_id);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.style.display = 'block';
    btn.disabled = false;
    btn.textContent = 'Tiếp tục thanh toán';
  }
});

function startCountdown() {
  var remaining = TIMEOUT_MS / 1000;
  var el = document.getElementById('countdown');

  countdownTimer = setInterval(function() {
    remaining--;
    if (remaining <= 0) {
      clearInterval(countdownTimer);
      clearInterval(pollTimer);
      showStep(4);
      return;
    }
    var m = Math.floor(remaining / 60);
    var s = remaining % 60;
    el.textContent = m + ':' + (s < 10 ? '0' : '') + s;

    if (remaining <= 300) {
      el.style.color = '#e74c3c';
    }
  }, 1000);
}

function startPolling(orderId) {
  pollRetries = 0;
  pollTimer = setInterval(async function() {
    try {
      var res = await fetch(API_BASE + '/api/status/' + orderId);
      if (!res.ok) throw new Error('status ' + res.status);
      var data = await res.json();
      pollRetries = 0;
      if (data.paid) {
        clearInterval(pollTimer);
        clearInterval(countdownTimer);
        var statusEl = document.getElementById('paymentStatus');
        statusEl.className = 'status-bar status-paid';
        statusEl.innerHTML = '&#10004; Thanh toán thành công!';
        if (data.order_status_url) {
          document.getElementById('orderLink').href = data.order_status_url;
        }
        setTimeout(function() { showStep(3); }, 1500);
      }
    } catch (e) {
      pollRetries++;
      if (pollRetries >= MAX_POLL_RETRIES) {
        var statusEl = document.getElementById('paymentStatus');
        statusEl.className = 'status-bar status-timeout';
        statusEl.innerHTML = '&#9888; Mất kết nối. Đang thử lại...';
        pollRetries = 0;
      }
    }
  }, POLL_MS);
}
</script>

</body>
</html>`;
}

// ── Main router ─────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(env, request) });
    }

    try {
      if (url.pathname === '/api/start-checkout' && request.method === 'POST') {
        return handleStartCheckout(request, env);
      }
      if (url.pathname === '/pay' && request.method === 'GET') {
        return handlePaymentPage(url, env);
      }
      if (url.pathname === '/api/create-order' && request.method === 'POST') {
        return handleCreateOrder(request, env);
      }
      if (url.pathname.startsWith('/api/status/') && request.method === 'GET') {
        return handleCheckStatus(url, env);
      }
      return new Response('Not Found', { status: 404 });
    } catch (err) {
      return jsonResponse({ error: err.message }, env, 500, request);
    }
  },
};
